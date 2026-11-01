"""Safe software connector registry and invocation service."""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.application.errors import ApplicationError
from app.domain.importer import ImportGuard
from app.domain.openapi_tools import parse_openapi_tools


def _now():
    return datetime.now(UTC).isoformat()


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

    def list_approvals(self, status=None, limit=100):
        rows = self.repo.list_approvals(status, limit)
        result = []
        for row in rows:
            decoded = self._decode(row)
            try:
                decoded["arguments"] = json.loads(row.get("arguments") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded["arguments"] = {}
            result.append(decoded)
        return result

    def create_tool(self, dto):
        if not self.repo.get_instance(dto.instance_id):
            raise ApplicationError("Software instance not found", 404, "not_found")
        return self._decode(self.repo.create_tool(dto.model_dump()))

    def update_tool(self, tool_id, values):
        return self._decode(self.repo.update_tool(tool_id, values))

    def delete_tool(self, tool_id):
        return self.repo.delete_tool(tool_id)

    def preview_openapi(self, spec):
        return parse_openapi_tools(spec)

    def import_openapi(self, name, spec, selected_tools=None):
        preview = parse_openapi_tools(spec)
        if selected_tools is not None:
            if not all(isinstance(item, str) for item in selected_tools):
                raise ApplicationError("Selected tool names are invalid", 422, "invalid_tool_selection")
            selected = set(selected_tools)
            available = {tool["name"] for tool in preview["tools"]}
            if selected - available:
                raise ApplicationError("Selected tool does not exist in the OpenAPI document", 422, "invalid_tool_selection")
            tools = [tool for tool in preview["tools"] if tool["name"] in selected]
        else:
            tools = preview["tools"]
        if not tools:
            raise ApplicationError("Select at least one OpenAPI operation", 422, "invalid_tool_selection")
        server_url = tools[0]["config"]["server_url"]
        instance_values = {
            "name": name,
            "connector_type": "openapi",
            "config": {"server_url": server_url},
            "enabled": True,
        }
        return self.repo.import_openapi(instance_values, tools)

    def set_tool_enabled(self, tool_id, enabled):
        return self.update_tool(tool_id, {"enabled": 1 if enabled else 0})

    def create_approval(self, tool_id, arguments, principal=None):
        tool = self.repo.get_tool(tool_id)
        if not tool or not tool.get("enabled"):
            raise ApplicationError("Software tool is unavailable", 404, "not_found")
        tool = self._decode(tool)
        self._validate_arguments(tool, arguments)
        return self.repo.create_approval({
            "tool_id": tool_id,
            "principal_type": getattr(principal, "principal_type", None),
            "principal_id": getattr(principal, "principal_id", None),
            "arguments": arguments,
            "status": "pending",
            "decision_by": None,
            "decision_at": None,
            "error_type": None,
        })

    def decide_approval(self, approval_id, approved, principal=None):
        request = self.repo.get_approval(approval_id)
        if not request:
            raise ApplicationError("Software approval request not found", 404, "not_found")
        if request.get("status") != "pending":
            raise ApplicationError("Software approval request is already decided", 409, "approval_conflict")
        decision_by = getattr(principal, "principal_id", None)
        if not approved:
            if not self.repo.update_approval(approval_id, {"status": "rejected", "decision_by": decision_by, "decision_at": _now()}, "pending"):
                raise ApplicationError("Software approval request is already decided", 409, "approval_conflict")
            return {"id": approval_id, "status": "rejected"}
        if not self.repo.update_approval(approval_id, {"status": "approved", "decision_by": decision_by, "decision_at": _now()}, "pending"):
            raise ApplicationError("Software approval request is already decided", 409, "approval_conflict")
        try:
            arguments = json.loads(request.get("arguments") or "{}")
            result = self.invoke(request["tool_id"], arguments, principal, approved=True)
        except Exception as exc:
            self.repo.update_approval(approval_id, {"status": "failed", "error_type": getattr(exc, "code", type(exc).__name__)})
            raise
        self.repo.update_approval(approval_id, {"status": "executed", "error_type": None})
        return {"id": approval_id, "status": "executed", "result": result}

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
                "request_summary": self._safe_summary(arguments),
                "response_summary": self._safe_summary(result) if status == "succeeded" else response_summary,
            })

    @staticmethod
    def _safe_summary(value):
        secret_name = re.compile(r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|credential|cookie|private[_-]?key)", re.IGNORECASE)
        bearer = re.compile(r"(?i)\bBearer\s+[^\s,;]+")

        def redact(item):
            if isinstance(item, dict):
                return {
                    key: "[REDACTED]" if secret_name.search(str(key)) else redact(child)
                    for key, child in item.items()
                }
            if isinstance(item, (list, tuple)):
                return [redact(child) for child in item]
            if isinstance(item, str):
                return bearer.sub("Bearer [REDACTED]", item)
            return item

        return json.dumps(redact(value), ensure_ascii=False, default=str)[:16_384]

    @staticmethod
    def _validate_arguments(tool, arguments):
        if not isinstance(arguments, dict):
            raise ApplicationError("Tool arguments must be an object", 422, "invalid_arguments")
        if len(json.dumps(arguments, ensure_ascii=False, default=str)) > 1_048_576:
            raise ApplicationError("Tool arguments exceed the size limit", 413, "size_limit")
        schema = tool.get("input_schema") or {}
        if not isinstance(schema, dict):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        SoftwareService._validate_schema_value(schema, arguments, "arguments")

    @staticmethod
    def _validate_schema_value(schema, value, label, depth=0):
        if depth > 32 or not isinstance(schema, dict):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        if not isinstance(properties, dict) or not isinstance(required, list) or not all(isinstance(name, str) for name in required):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        expected = schema.get("type")
        if expected is None and "properties" in schema:
            expected = "object"
        expected_types = [expected] if isinstance(expected, str) else expected if isinstance(expected, list) else []
        if expected_types and not all(isinstance(item, str) for item in expected_types):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        type_checks = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "null": value is None,
        }
        if any(item not in type_checks for item in expected_types):
            raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
        valid = any(type_checks[item] for item in expected_types) if expected_types else True
        valid = valid or (value is None and schema.get("nullable") is True)
        if not valid:
            raise ApplicationError(f"Tool argument '{label}' has an invalid type", 422, "invalid_arguments")
        if "enum" in schema:
            if not isinstance(schema["enum"], list):
                raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
            if value not in schema["enum"]:
                raise ApplicationError(f"Tool argument '{label}' is not an allowed value", 422, "invalid_arguments")
        if isinstance(value, str):
            minimum = schema.get("minLength", 0)
            maximum = schema.get("maxLength")
            if isinstance(minimum, bool) or not isinstance(minimum, int) or (maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int))):
                raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
            if len(value) < minimum or (maximum is not None and len(value) > maximum):
                raise ApplicationError(f"Tool argument '{label}' has an invalid length", 422, "invalid_arguments")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                raise ApplicationError(f"Tool argument '{label}' is below the minimum", 422, "invalid_arguments")
            if "maximum" in schema and value > schema["maximum"]:
                raise ApplicationError(f"Tool argument '{label}' exceeds the maximum", 422, "invalid_arguments")
        if isinstance(value, dict):
            missing = [name for name in required if name not in value]
            if missing:
                raise ApplicationError(f"Required tool arguments are missing from '{label}'", 422, "invalid_arguments")
            if schema.get("additionalProperties") is False:
                unknown = sorted(set(value) - set(properties))
                if unknown:
                    raise ApplicationError(f"Unknown tool arguments are not allowed in '{label}'", 422, "invalid_arguments")
            for name, child in value.items():
                child_schema = properties.get(name)
                if child_schema is not None:
                    SoftwareService._validate_schema_value(child_schema, child, f"{label}.{name}", depth + 1)
                elif isinstance(schema.get("additionalProperties"), dict):
                    SoftwareService._validate_schema_value(schema["additionalProperties"], child, f"{label}.{name}", depth + 1)
        if isinstance(value, list):
            minimum = schema.get("minItems", 0)
            maximum = schema.get("maxItems")
            if isinstance(minimum, bool) or not isinstance(minimum, int) or (maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int))):
                raise ApplicationError("Tool input schema is invalid", 422, "invalid_tool_config")
            if len(value) < minimum or (maximum is not None and len(value) > maximum):
                raise ApplicationError(f"Tool argument '{label}' has an invalid item count", 422, "invalid_arguments")
            item_schema = schema.get("items")
            if item_schema is not None:
                for index, item in enumerate(value):
                    SoftwareService._validate_schema_value(item_schema, item, f"{label}[{index}]", depth + 1)

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
        if connector == "openapi":
            return self._invoke_openapi(config, arguments)
        if connector in {"http", "wechat", "clihub"}:
            url = str(config.get("url") or "")
            if not url and connector != "http":
                raise ApplicationError("Connector is registered but not configured", 501, "connector_not_implemented")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ApplicationError("HTTP connector URL is invalid", 422, "invalid_tool_config")
            ImportGuard.remote_url(url)
            try:
                timeout = min(max(float(config.get("timeout_seconds", 30)), 1.0), 120.0)
            except (TypeError, ValueError):
                timeout = 30.0
            response = httpx.request(str(config.get("method", "POST")).upper(), url, json=arguments, headers=config.get("headers") or {}, timeout=timeout, follow_redirects=False)
            if response.status_code >= 400:
                raise ApplicationError("HTTP tool returned an error", 502, "tool_execution_failed")
            if len(response.content) > 1_048_576:
                raise ApplicationError("HTTP tool response exceeds the size limit", 502, "response_too_large")
            try:
                return response.json()
            except ValueError:
                return {"text": response.text[:16_384]}
        if connector == "mcp":
            return self._invoke_mcp(config, tool["name"], arguments)
        raise ApplicationError("Unsupported software connector", 422, "invalid_tool_config")

    @staticmethod
    def _invoke_openapi(config, arguments):
        server = str(config.get("server_url") or "")
        path = str(config.get("path") or "")
        method = str(config.get("method") or "").upper()
        bindings = config.get("bindings") or []
        if not path.startswith("/") or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not isinstance(bindings, list):
            raise ApplicationError("OpenAPI tool configuration is invalid", 422, "invalid_tool_config")
        path_values = {}
        query = {}
        for binding in bindings:
            if not isinstance(binding, dict):
                raise ApplicationError("OpenAPI tool configuration is invalid", 422, "invalid_tool_config")
            field, location, name = binding.get("field"), binding.get("in"), binding.get("name")
            if not isinstance(field, str) or not isinstance(name, str):
                raise ApplicationError("OpenAPI tool configuration is invalid", 422, "invalid_tool_config")
            if field not in arguments:
                continue
            if location == "path":
                from urllib.parse import quote

                path_values[name] = quote(str(arguments[field]), safe="")
            elif location == "query":
                value = arguments[field]
                if isinstance(value, list) and not binding.get("explode", True):
                    query[name] = ",".join(str(item) for item in value)
                else:
                    query[name] = value
            else:
                raise ApplicationError("OpenAPI tool parameter location is invalid", 422, "invalid_tool_config")
        for name, value in path_values.items():
            path = path.replace("{" + name + "}", value)
        if "{" in path or "}" in path:
            raise ApplicationError("OpenAPI path parameter is missing", 422, "invalid_arguments")
        from urllib.parse import urlparse

        parsed_server = urlparse(server)
        if parsed_server.scheme not in {"http", "https"} or not parsed_server.hostname:
            raise ApplicationError("OpenAPI server URL is invalid", 422, "invalid_tool_config")
        url = server.rstrip("/") + "/" + path.lstrip("/")
        ImportGuard.remote_url(url)
        body_field = config.get("body_field")
        payload = arguments.get(body_field) if isinstance(body_field, str) else None
        response = httpx.request(
            method, url, params=query,
            json=payload if isinstance(body_field, str) else None,
            timeout=30.0, follow_redirects=False,
        )
        if response.status_code >= 400:
            raise ApplicationError("OpenAPI operation returned an error", 502, "tool_execution_failed")
        if len(response.content) > 1_048_576:
            raise ApplicationError("OpenAPI response exceeds the size limit", 502, "response_too_large")
        try:
            return response.json()
        except ValueError:
            return {"text": response.text[:16_384], "status_code": response.status_code}

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
        headers = {
            **configured_headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": str(config.get("protocol_version") or "2025-06-18"),
        }

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
        notify_headers = dict(headers)
        if session_id:
            notify_headers["Mcp-Session-Id"] = session_id
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        notification = httpx.post(url, json=initialized, headers=notify_headers, timeout=timeout, follow_redirects=False)
        if notification.status_code not in {200, 202, 204}:
            raise ApplicationError("MCP server initialization failed", 502, "tool_execution_failed")
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
