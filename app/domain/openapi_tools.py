"""Parse a bounded OpenAPI document into safe, invokable software tools."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from app.application.errors import ApplicationError

MAX_SPEC_BYTES = 1_048_576
MAX_OPERATIONS = 100
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
UNSUPPORTED_SCHEMA_KEYWORDS = {
    "pattern", "patternProperties", "oneOf", "anyOf", "allOf", "not", "if", "then", "else",
    "minProperties", "maxProperties", "uniqueItems", "multipleOf", "exclusiveMinimum", "exclusiveMaximum",
    "contains", "propertyNames", "dependentSchemas", "dependencies", "unevaluatedItems", "unevaluatedProperties",
}


def _invalid(message: str) -> ApplicationError:
    return ApplicationError(message, 422, "invalid_openapi_spec")


def _resolve_ref(spec: dict, value: Any, seen: frozenset[str] = frozenset(), depth: int = 0):
    if depth > 32:
        raise _invalid("OpenAPI references exceed the maximum depth")
    if isinstance(value, list):
        return [_resolve_ref(spec, item, seen, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if ref is None:
        return {key: _resolve_ref(spec, item, seen, depth + 1) for key, item in value.items()}
    if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
        raise _invalid("Only non-cyclic local OpenAPI references are supported")
    target = spec
    try:
        for segment in ref[2:].split("/"):
            segment = segment.replace("~1", "/").replace("~0", "~")
            target = target[int(segment)] if isinstance(target, list) else target[segment]
    except (IndexError, KeyError, TypeError, ValueError):
        raise _invalid("OpenAPI document contains an unresolved reference") from None
    if not isinstance(target, (dict, list)):
        raise _invalid("OpenAPI references must point to objects")
    resolved = _resolve_ref(spec, target, seen | {ref}, depth + 1)
    siblings = {key: item for key, item in value.items() if key != "$ref"}
    if siblings and isinstance(resolved, dict):
        resolved = {**resolved, **_resolve_ref(spec, siblings, seen | {ref}, depth + 1)}
    return resolved


def _server_url(spec: dict, path_item: dict, operation: dict) -> str:
    servers = operation.get("servers") or path_item.get("servers") or spec.get("servers") or []
    if not servers or not isinstance(servers, list) or not isinstance(servers[0], dict):
        raise _invalid("OpenAPI document must define a server URL")
    server = servers[0]
    url = server.get("url")
    variables = server.get("variables") or {}
    if not isinstance(url, str) or not isinstance(variables, dict):
        raise _invalid("OpenAPI server definition is invalid")
    for name, definition in variables.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise _invalid("OpenAPI server variable is invalid")
        default = definition.get("default")
        if isinstance(default, bool) or not isinstance(default, (str, int, float)):
            raise _invalid("OpenAPI server variables require a string default")
        url = url.replace("{" + name + "}", str(default))
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise _invalid("OpenAPI server URL is invalid") from exc
    if (
        "{" in url
        or "}" in url
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise _invalid("OpenAPI server URL must be an absolute HTTP URL without credentials or query")
    try:
        port = parsed.port
    except ValueError as exc:
        raise _invalid("OpenAPI server URL port is invalid") from exc
    if port == 0:
        raise _invalid("OpenAPI server URL port is invalid")
    return url.rstrip("/")


def _validate_schema_definition(schema: dict, depth: int = 0) -> None:
    if depth > 32 or not isinstance(schema, dict):
        raise _invalid("OpenAPI schema exceeds the supported depth or shape")
    if UNSUPPORTED_SCHEMA_KEYWORDS.intersection(schema):
        raise _invalid("OpenAPI schema uses validation keywords that are not supported")
    if "nullable" in schema and not isinstance(schema["nullable"], bool):
        raise _invalid("OpenAPI nullable must be a boolean")
    expected = schema.get("type")
    allowed_types = {"string", "number", "integer", "boolean", "object", "array", "null"}
    if isinstance(expected, list):
        if not expected or not all(isinstance(item, str) and item in allowed_types for item in expected):
            raise _invalid("OpenAPI schema type union is invalid")
    elif expected is not None and (not isinstance(expected, str) or expected not in allowed_types):
        raise _invalid("OpenAPI schema type is unsupported")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise _invalid("OpenAPI enum must be a list")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], int) or schema[key] < 0):
            raise _invalid(f"OpenAPI {key} must be a non-negative integer")
    for key in ("minimum", "maximum"):
        if key in schema and (isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))):
            raise _invalid(f"OpenAPI {key} must be numeric")
    if "properties" in schema:
        properties = schema["properties"]
        if not isinstance(properties, dict):
            raise _invalid("OpenAPI properties must be an object")
        for child in properties.values():
            _validate_schema_definition(child, depth + 1)
    if "required" in schema and (not isinstance(schema["required"], list) or not all(isinstance(name, str) for name in schema["required"])):
        raise _invalid("OpenAPI required must be a list of property names")
    if "required" in schema and isinstance(schema.get("properties"), dict) and not set(schema["required"]).issubset(schema["properties"]):
        raise _invalid("OpenAPI required properties must be declared")
    if "items" in schema:
        _validate_schema_definition(schema["items"], depth + 1)
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], (bool, dict)):
        raise _invalid("OpenAPI additionalProperties must be a boolean or schema")
    if isinstance(schema.get("additionalProperties"), dict):
        _validate_schema_definition(schema["additionalProperties"], depth + 1)


def _operation_name(operation: dict, method: str, path: str, used: set[str]) -> str:
    raw = operation.get("operationId") or f"{method}_{path}"
    if not isinstance(raw, str):
        raise _invalid("OpenAPI operationId must be a string")
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_.-") or f"{method}_operation"
    name = base[:120]
    suffix = 2
    while name in used:
        tail = f"_{suffix}"
        name = base[: 120 - len(tail)] + tail
        suffix += 1
    used.add(name)
    return name


def parse_openapi_tools(spec: dict) -> dict:
    """Return normalized tool definitions; never fetches refs or server URLs."""
    if not isinstance(spec, dict):
        raise _invalid("OpenAPI document must be a JSON object")
    try:
        if len(json.dumps(spec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_SPEC_BYTES:
            raise ApplicationError("OpenAPI document exceeds the size limit", 413, "size_limit")
    except (RecursionError, TypeError, ValueError) as exc:
        raise _invalid("OpenAPI document is not valid JSON data") from exc
    version = spec.get("openapi")
    if not isinstance(version, str) or not version.startswith(("3.0.", "3.1.")):
        raise _invalid("Only OpenAPI 3.0 and 3.1 documents are supported")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise _invalid("OpenAPI document must define paths")

    tools: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for path, raw_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(raw_item, dict):
            raise _invalid("OpenAPI path definition is invalid")
        if "?" in path or "#" in path or "\\" in path or any(segment in {".", ".."} for segment in path.split("/")):
            raise _invalid("OpenAPI paths cannot contain query, fragment, backslash or traversal segments")
        path_item = _resolve_ref(spec, raw_item) if "$ref" in raw_item else raw_item
        if not isinstance(path_item, dict):
            raise _invalid("OpenAPI path definition is invalid")
        for method, raw_operation in path_item.items():
            if not isinstance(method, str):
                continue
            method = method.lower()
            if method not in HTTP_METHODS:
                continue
            operation = raw_operation
            if not isinstance(operation, dict):
                raise _invalid("OpenAPI operation definition is invalid")
            if len(tools) >= MAX_OPERATIONS:
                raise ApplicationError("OpenAPI document has too many operations", 413, "size_limit")
            tool_name = _operation_name(operation, method, path, used_names)
            path_params = re.findall(r"\{([^{}]+)\}", path)
            parameter_map: dict[tuple[str, str], dict] = {}
            for source in (path_item.get("parameters") or [], operation.get("parameters") or []):
                if not isinstance(source, list):
                    raise _invalid("OpenAPI parameters must be a list")
                for raw_parameter in source:
                    parameter = _resolve_ref(spec, raw_parameter)
                    if not isinstance(parameter, dict):
                        raise _invalid("OpenAPI parameter is invalid")
                    location, name = parameter.get("in"), parameter.get("name")
                    if not isinstance(location, str) or location not in {"path", "query"} or not isinstance(name, str) or not name:
                        raise _invalid("Only named path and query parameters can be imported")
                    schema = _resolve_ref(spec, parameter.get("schema") or {"type": "string"})
                    if not isinstance(schema, dict):
                        raise _invalid("OpenAPI parameter schema is invalid")
                    _validate_schema_definition(schema)
                    schema_type = schema.get("type")
                    schema_types = {schema_type} if isinstance(schema_type, str) else set(schema_type) if isinstance(schema_type, list) else set()
                    if "object" in schema_types or (location == "path" and "array" in schema_types):
                        raise _invalid("OpenAPI parameter schema shape is unsupported")
                    if parameter.get("style") not in (None, "simple" if location == "path" else "form"):
                        raise _invalid("OpenAPI parameter serialization style is unsupported")
                    if "explode" in parameter and not isinstance(parameter["explode"], bool):
                        raise _invalid("OpenAPI parameter explode must be a boolean")
                    parameter_map[(location, name)] = {
                        "required": location == "path" or bool(parameter.get("required")),
                        "schema": schema,
                        "explode": parameter.get("explode", location == "query"),
                    }
            declared_path_params = {name for location, name in parameter_map if location == "path"}
            if set(path_params) != declared_path_params:
                raise _invalid("Path template variables and path parameters must match")

            properties = {}
            required = []
            bindings = []
            for (location, name), parameter in parameter_map.items():
                field_name = f"{location}__{name}"
                properties[field_name] = parameter["schema"]
                bindings.append({"field": field_name, "in": location, "name": name, "explode": parameter["explode"]})
                if parameter["required"]:
                    required.append(field_name)

            request_body = operation.get("requestBody")
            body_field = None
            if request_body is not None:
                request_body = _resolve_ref(spec, request_body)
                content = request_body.get("content") if isinstance(request_body, dict) else None
                media = content.get("application/json") if isinstance(content, dict) else None
                if not isinstance(media, dict):
                    raise _invalid("Only application/json request bodies can be imported")
                body_schema = _resolve_ref(spec, media.get("schema") or {"type": "object"})
                if not isinstance(body_schema, dict):
                    raise _invalid("OpenAPI request body schema is invalid")
                _validate_schema_definition(body_schema)
                body_field = "body"
                properties[body_field] = body_schema
                if request_body.get("required"):
                    required.append(body_field)

            details = operation.get("description") or operation.get("summary") or ""
            if not isinstance(details, str):
                raise _invalid("OpenAPI operation description must be a string")
            tools.append({
                "name": tool_name,
                "description": details[:4096],
                "risk_level": "medium",
                "approval_mode": "per_call",
                "input_schema": {
                    "type": "object", "properties": properties,
                    "required": required, "additionalProperties": False,
                },
                "config": {
                    "server_url": _server_url(spec, path_item, operation),
                    "path": path,
                    "method": method.upper(),
                    "bindings": bindings,
                    "body_field": body_field,
                },
            })
    if not tools:
        raise _invalid("OpenAPI document contains no supported operations")
    return {"openapi": version, "tool_count": len(tools), "tools": tools}
