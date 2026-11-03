"""Shared credential-field classification."""
import re

SECRET_FIELDS = frozenset({
    "api_key", "apikey", "secret", "secret_key", "access_key", "access_token",
    "auth_token", "token", "password", "passwd", "authorization", "cookie",
    "session", "sessionid", "private_key", "client_secret", "aws_secret_access_key",
    "secretkey", "secret_id", "secretid", "accesskeyid", "access_key_id",
})


def is_secret_field(key: str) -> bool:
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", key).lower().replace("-", "_")
    return normalized in SECRET_FIELDS


def structured_tool_name(value: dict, path: str, inherited=None):
    function = value.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    if isinstance(value.get("name"), str) and (
        value.get("type") in {"tool_use", "function_call", "custom_tool_call"}
        or any(part in path for part in (".tools[", ".tool_calls[", ".function"))
    ):
        return value["name"]
    return inherited
