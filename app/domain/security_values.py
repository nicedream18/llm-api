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
