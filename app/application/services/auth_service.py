"""Authentication and authorization primitives for admin and data-plane access."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

from app.config import config
from app.domain.entities import ApiKeyEntity
from app.types.auth import AuthContext


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401, code: str = "authentication_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def hash_password(password: str) -> str:
    """Portable password hash. Argon2 hashes are accepted when argon2-cffi is installed."""
    try:
        from argon2 import PasswordHasher
        return PasswordHasher().hash(password)
    except ImportError:
        iterations = 310_000
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    if not encoded:
        return False
    if encoded.startswith("$argon2"):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import InvalidHashError, VerificationError
            try:
                return bool(PasswordHasher().verify(encoded, password))
            except (InvalidHashError, VerificationError, TypeError):
                return False
        except ImportError:
            return False
    try:
        scheme, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(raw_iterations)
        salt = base64.urlsafe_b64decode(raw_salt.encode())
        expected = base64.urlsafe_b64decode(raw_digest.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64_json(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")


def _unb64_json(value: str) -> dict[str, Any]:
    return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode())


class AdminAuthService:
    def __init__(self, repository=None):
        self.repository = repository
        self._failed: dict[str, deque[float]] = defaultdict(deque)

    @property
    def username(self) -> str:
        return config.auth.admin_username

    def _password_hash(self) -> str:
        configured = config.auth.admin_password_hash
        if self.repository:
            user = self.repository.get_user(self.username)
            if user and user["status"] == 1:
                return user["password_hash"]
        if configured:
            return configured
        return hash_password(config.auth.bootstrap_password) if config.auth.bootstrap_password else ""

    def _check_rate_limit(self, client_ip: str | None) -> None:
        if not client_ip:
            return
        now = time.time()
        attempts = self._failed[client_ip]
        while attempts and attempts[0] <= now - 60:
            attempts.popleft()
        if len(attempts) >= 5:
            raise AuthError("Invalid credentials", 401, "authentication_error")

    def login(self, username: str, password: str, client_ip: str | None = None) -> str:
        self._check_rate_limit(client_ip)
        stored_hash = self._password_hash()
        # Perform a password hash verification even for an unknown account to reduce timing leaks.
        valid_password = verify_password(password, stored_hash) if stored_hash else verify_password(
            password, "pbkdf2_sha256$310000$MDEyMzQ1Njc4OWFiY2RlZg==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        )
        valid = hmac.compare_digest(username, self.username) and bool(stored_hash) and valid_password
        if not valid:
            if client_ip:
                self._failed[client_ip].append(time.time())
            raise AuthError("Invalid credentials", 401, "authentication_error")
        if client_ip:
            self._failed.pop(client_ip, None)
        return self.create_session(username)

    def create_session(self, username: str | None = None) -> str:
        secret = config.auth.session_secret
        if not secret:
            raise AuthError("Admin sessions are not configured", 503, "configuration_error")
        now = int(time.time())
        payload = {"sub": username or self.username, "iat": now, "exp": now + config.auth.session_ttl_seconds}
        body = _b64_json(payload)
        signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        return f"{body}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"

    def verify_session(self, token: str | None) -> AuthContext | None:
        if not token or not config.auth.session_secret:
            return None
        try:
            body, encoded_signature = token.split(".", 1)
            provided = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
            expected = hmac.new(config.auth.session_secret.encode(), body.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(provided, expected):
                return None
            payload = _unb64_json(body)
            if int(payload.get("exp", 0)) <= int(time.time()):
                return None
            return AuthContext("admin", str(payload.get("sub") or self.username), str(payload.get("sub") or self.username))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def verify_admin_token(self, token: str | None) -> AuthContext | None:
        expected = config.auth.admin_token
        if expected and token and hmac.compare_digest(token, expected):
            return AuthContext("admin", "admin-token", self.username)
        return None


class ApiKeyAuthorizer:
    def __init__(self, repository):
        self.repository = repository

    def authenticate(self, raw_key: str | None) -> AuthContext:
        if not raw_key:
            raise AuthError("Missing API key", 401, "authentication_error")
        entity: ApiKeyEntity | None = self.repository.get_api_key_by_key(raw_key)
        if not entity or entity.status != 1:
            raise AuthError("Invalid API key", 401, "authentication_error")
        if entity.expires_at:
            try:
                expires = datetime.fromisoformat(entity.expires_at)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires <= datetime.now(UTC):
                    raise AuthError("API key expired", 401, "authentication_error")
            except ValueError:
                raise AuthError("API key configuration is invalid", 401, "authentication_error")
        return AuthContext(
            principal_type="api_key", principal_id=entity.id or "", principal_name=entity.name,
            allowed_models=frozenset(entity.allowed_models or []),
            allowed_channels=frozenset(entity.allowed_channels or []),
            quota_limit=int(entity.quota_limit or 0) or None,
            quota_used=int(entity.quota_used or 0),
            raw_key_fingerprint=fingerprint(raw_key),
        )

    @staticmethod
    def authorize_request(context: AuthContext, model: str | None = None, channel_id: str | None = None) -> None:
        if not context.is_api_key:
            return
        if model and context.allowed_models and model not in context.allowed_models:
            raise AuthError("Model is not allowed for this API key", 403, "permission_error")
        if channel_id and context.allowed_channels and channel_id not in context.allowed_channels:
            raise AuthError("Channel is not allowed for this API key", 403, "permission_error")
