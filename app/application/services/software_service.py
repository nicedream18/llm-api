"""Safe software connector registry and invocation service."""

from __future__ import annotations

import json
import subprocess
import time
from urllib.parse import urlparse

import httpx

from app.application.errors import ApplicationError
from app.domain.importer import ImportGuard


class SoftwareService:
    def __init__(self, repository):
        self.repo = repository

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("config", "input_schema"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (TypeError, ValueError, json.JSONDecodeError):
                    result[key] = {}
        return result

    def list_instances(self):
        return [self._decode(row) for row in self.repo.list_instances()]

    def create_instance(self, dto):
        return self._decode(self.repo.create_instance(dto.model_dump()))

    def update_instance(self, instance_id, dto):
        values = dto.model_dump(exclude_unset=True)
        return self._decode(self.repo.update_instance(instance_id, values))

    def delete_instance(self, instance_id):
        return self.repo.delete_instance(instance_id)

    def list_tools(self, instance_id=None):
        return [self._decode(row) for row in self.repo.list_tools(instance_id)]

    def create_tool(self, dto):
        if not self.repo.get_instance(dto.instance_id):
            raise ApplicationError("Software instance not found", 404, "not_found")
        return self._decode(self.repo.create_tool(dto.model_dump()))

    def update_tool(self, tool_id, values):
        return self._decode(self.repo.update_tool(tool_id, values))

    def delete_tool(self, tool_id):
        return self.repo.delete_tool(tool_id)

    def set_tool_enabled(self, tool_id, enabled):
        return self.update_tool(tool_id, {"enabled": 1 if enabled else 0})

    def invoke(self, tool_id, arguments, principal=None, approved=False):
        tool = self.repo.get_tool(tool_id)
        if not tool or not tool.get("enabled"):
            raise ApplicationError("Software tool is unavailable", 404, "not_found")
        tool = self._decode(tool)
        if tool["approval_mode"] != "none" and not approved:
            raise ApplicationError("Tool approval is required", 403, "approval_required")
        started = time.monotonic()
        status = "failed"
        error_type = None
        response_summary = None
        try:
            self._validate_arguments(tool, arguments)
            instance = self.repo.get_instance(tool["instance_id"])
            if not instance or not instance.get("enabled"):
                raise ApplicationError("Software instance is unavailable", 404, "not_found")
            instance = self._decode(instance)
            result = self._invoke_connector(instance, tool, arguments)
            status = "succeeded"
            response_summary = json.dumps(result, ensure_ascii=False, default=str)[:16_384]
            return result
        except ApplicationError as exc:
            error_type = exc.code
            raise
        except (OSError, ValueError, TypeError, httpx.HTTPError) as exc:
            error_type = type(exc).__name__
            raise ApplicationError("Software tool execution failed", 502, "tool_execution_failed") from exc
        finally:
            self.repo.record_call({
                "tool_id": tool_id,
                "principal_type": getattr(principal, "principal_type", None),
                "principal_id": getattr(principal, "principal_id", None),
                "status": status,
                "error_type": error_type,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "request_summary": json.dumps(arguments, ensure_ascii=False, default=str)[:16_384],
                "response_summary": response_summary,
            })

    @staticmethod
    def _validate_arguments(tool, arguments):
        if not isinstance(arguments, dict):
            raise ApplicationError("Tool arguments must be an object", 422, "invalid_arguments")
        if len(json.dumps(arguments, ensure_ascii=False, default=str)) > 1_048_576:
            raise ApplicationError("Tool arguments exceed the size limit", 413, "size_limit")
        schema = tool.get("input_schema") or {}
        if not isinstance(schema, dict):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        required = schema.get("required") or []
        if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        missing = [name for name in required if name not in arguments]
        if missing:
            raise ApplicationError("Required tool arguments are missing", 422, "invalid_arguments")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(arguments) - set(properties))
            if unknown:
                raise ApplicationError("Unknown tool arguments are not allowed", 422, "invalid_arguments")
        for name, value in arguments.items():
            definition = properties.get(name)
            if not isinstance(definition, dict):
                continue
            expected = definition.get("type")
            valid = {
                "string": isinstance(value, str),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
                "null": value is None,
            }.get(expected, True)
            if not valid:
                raise ApplicationError(f"Tool argument '{name}' has an invalid type", 422, "invalid_arguments")

    def _invoke_connector(self, instance, tool, arguments):
        connector = instance["connector_type"]
        config = {**(instance.get("config") or {}), **(tool.get("config") or {})}
        if connector == "cli":
            command = config.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                raise ApplicationError("CLI connector requires an argv command", 422, "invalid_tool_config")
            argv = command + [str(arguments[key]) for key in sorted(arguments)]
            result = subprocess.run(argv, shell=False, check=False, capture_output=True, text=True, timeout=min(int(config.get("timeout_seconds", 30)), 120))
            if result.returncode != 0:
                raise ApplicationError("CLI tool returned an error", 502, "tool_execution_failed")
            return {"stdout": result.stdout[:16_384], "returncode": result.returncode}
        if connector == "http":
            url = str(config.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ApplicationError("HTTP connector URL is invalid", 422, "invalid_tool_config")
            ImportGuard.remote_url(url)
            response = httpx.request(str(config.get("method", "POST")).upper(), url, json=arguments, timeout=min(float(config.get("timeout_seconds", 30)), 120), follow_redirects=False)
            if response.status_code >= 400:
                raise ApplicationError("HTTP tool returned an error", 502, "tool_execution_failed")
            try:
                return response.json()
            except ValueError:
                return {"text": response.text[:16_384]}
        if connector in {"mcp", "wechat", "clihub"}:
            raise ApplicationError("Connector is registered but not configured", 501, "connector_not_implemented")
        raise ApplicationError("Unsupported software connector", 422, "invalid_tool_config")
