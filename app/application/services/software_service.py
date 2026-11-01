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
        if connector == "mcp":
            return self._invoke_mcp(config, tool["name"], arguments)
        if connector in {"wechat", "clihub"}:
            raise ApplicationError("Connector is registered but not configured", 501, "connector_not_implemented")
        raise ApplicationError("Unsupported software connector", 422, "invalid_tool_config")

    @staticmethod
    def _invoke_mcp(config, tool_name, arguments):
        url = str(config.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ApplicationError("MCP connector URL is invalid", 422, "invalid_tool_config")
        ImportGuard.remote_url(url)
        configured_headers = config.get("headers") or {}
        if not isinstance(configured_headers, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in configured_headers.items()):
            raise ApplicationError("MCP connector headers are invalid", 422, "invalid_tool_config")
        try:
            timeout = min(max(float(config.get("timeout_seconds", 30)), 1.0), 120.0)
        except (TypeError, ValueError):
            timeout = 30.0
        headers = {**configured_headers, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

        def call(payload, session_id=None):
            request_headers = dict(headers)
            if session_id:
                request_headers["Mcp-Session-Id"] = session_id
            response = httpx.post(url, json=payload, headers=request_headers, timeout=timeout, follow_redirects=False)
            if response.status_code < 200 or response.status_code >= 300:
                raise ApplicationError("MCP server returned an error", 502, "tool_execution_failed")
            if len(response.content) > 1_048_576:
                raise ApplicationError("MCP server response exceeds the size limit", 502, "response_too_large")
            return response, SoftwareService._decode_mcp_response(response)

        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": str(config.get("protocol_version") or "2025-06-18"),
                "capabilities": {},
                "clientInfo": {"name": "waliapi-software", "version": "1.0"},
            },
        }
        initialize_response, initialize_payload = call(initialize)
        if not isinstance(initialize_payload, dict) or initialize_payload.get("error"):
            raise ApplicationError("MCP server initialization failed", 502, "tool_execution_failed")
        session_id = initialize_response.headers.get("mcp-session-id")
        call_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": str(config.get("tool_name") or tool_name), "arguments": arguments},
        }
        _, result = call(call_payload, session_id)
        if not isinstance(result, dict):
            raise ApplicationError("MCP server returned an invalid response", 502, "tool_execution_failed")
        if result.get("error"):
            raise ApplicationError("MCP tool returned an error", 502, "tool_execution_failed")
        return result.get("result", result)

    @staticmethod
    def _decode_mcp_response(response):
        content_type = response.headers.get("content-type", "").lower()
        if "json" in content_type:
            try:
                return response.json()
            except ValueError as exc:
                raise ApplicationError("MCP server returned invalid JSON", 502, "tool_execution_failed") from exc
        for line in reversed(response.text.splitlines()):
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        raise ApplicationError("MCP server returned an invalid response", 502, "tool_execution_failed")
