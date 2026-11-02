"""Validated application configuration loaded from environment."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return default if value is None else value


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw or default)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _bool(name: str, default: bool) -> bool:
    return (_env(name, "true" if default else "false") or "").lower() in {"1", "true", "yes", "on"}


def _previous_keys():
    values = json.loads(_env("PROVIDER_TOKEN_PREVIOUS_KEYS", "[]") or "[]")
    if not isinstance(values, list):
        raise TypeError("PROVIDER_TOKEN_PREVIOUS_KEYS must be a JSON array")
    return tuple(values)


@dataclass(frozen=True)
class DatabaseConfig:
    unix_socket: str | None = field(default_factory=lambda: _env("DB_UNIX_SOCKET") or None)
    host: str = field(default_factory=lambda: _env("DB_HOST", "127.0.0.1") or "127.0.0.1")
    port: int = field(default_factory=lambda: _int("DB_PORT", 3306, 1))
    name: str = field(default_factory=lambda: _env("DB_NAME", "waliapi") or "waliapi")
    user: str = field(default_factory=lambda: _env("DB_USER", "root") or "root")
    password: str = field(default_factory=lambda: _env("DB_PASSWORD", "") or "")
    pool_size: int = field(default_factory=lambda: _int("DB_POOL_SIZE", 15, 1))
    max_overflow: int = field(default_factory=lambda: _int("DB_MAX_OVERFLOW", 10, 0))

    @property
    def url(self) -> str:
        if not self.password and (_env("APP_ENV", "development") or "development").lower() == "production":
            raise ValueError("DB_PASSWORD is required in production")
        from urllib.parse import quote_plus
        suffix = "&unix_socket=" + quote_plus(self.unix_socket) if self.unix_socket else ""
        return f"mysql+pymysql://{quote_plus(self.user)}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.name}?charset=utf8mb4{suffix}"


@dataclass(frozen=True)
class SecuritySettings:
    enabled: bool = field(default_factory=lambda: _bool("SECURITY_ENABLED", True))
    mode: str = field(default_factory=lambda: _env("SECURITY_MODE", "audit") or "audit")
    scan_unicode: bool = field(default_factory=lambda: _bool("SCAN_UNICODE", True))
    scan_tools: bool = field(default_factory=lambda: _bool("SCAN_TOOLS", True))
    scan_network: bool = field(default_factory=lambda: _bool("SCAN_NETWORK", True))
    scan_response: bool = field(default_factory=lambda: _bool("SCAN_RESPONSE", False))
    redact_secrets: bool = field(default_factory=lambda: _bool("REDACT_SECRETS", True))
    block_on_critical: bool = field(default_factory=lambda: _bool("BLOCK_ON_CRITICAL", True))
    fail_closed: bool = field(default_factory=lambda: _bool("SECURITY_FAIL_CLOSED", True))

    def __post_init__(self):
        if self.mode not in {"audit", "warn", "redact", "block"}:
            raise ValueError("SECURITY_MODE must be audit, warn, redact, or block")


@dataclass(frozen=True)
class GatewayConfig:
    retry_times: int = field(default_factory=lambda: _int("GATEWAY_RETRY_TIMES", 2, 0))
    retry_backoff_ms: int = field(default_factory=lambda: _int("GATEWAY_RETRY_BACKOFF_MS", 100, 0))
    request_timeout_seconds: float = field(default_factory=lambda: float(_env("GATEWAY_REQUEST_TIMEOUT_SECONDS", "300") or "300"))
    stream_timeout_seconds: float = field(default_factory=lambda: float(_env("GATEWAY_STREAM_TIMEOUT_SECONDS", "300") or "300"))
    max_response_log_bytes: int = field(default_factory=lambda: _int("MAX_RESPONSE_LOG_BYTES", 65536, 1024))
    channel_cooldown_seconds: int = field(default_factory=lambda: _int("GATEWAY_CHANNEL_COOLDOWN_SECONDS", 30, 0))
    retry_after_max_seconds: int = field(default_factory=lambda: _int("GATEWAY_RETRY_AFTER_MAX_SECONDS", 60, 0))

    def __post_init__(self):
        if self.request_timeout_seconds <= 0 or self.stream_timeout_seconds <= 0:
            raise ValueError("Gateway timeouts must be positive")


@dataclass(frozen=True)
class AuthConfig:
    provider_token_previous_keys: tuple[str, ...] = field(default_factory=_previous_keys)
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", "admin") or "admin")
    admin_password_hash: str = field(default_factory=lambda: _env("ADMIN_PASSWORD_HASH", "") or "")
    admin_token: str = field(default_factory=lambda: _env("ADMIN_TOKEN", "") or "")
    session_secret: str = field(default_factory=lambda: _env("ADMIN_SESSION_SECRET", "") or "")
    session_ttl_seconds: int = field(default_factory=lambda: _int("ADMIN_SESSION_TTL_SECONDS", 86400, 60))
    session_cookie_secure: bool = field(default_factory=lambda: _bool("ADMIN_SESSION_COOKIE_SECURE", (_env("APP_ENV", "development") or "development").lower() == "production"))
    models_require_api_key: bool = field(default_factory=lambda: _bool("MODELS_REQUIRE_API_KEY", True))
    mcp_token: str = field(default_factory=lambda: _env("MCP_TOKEN", "") or "")
    bootstrap_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", "") or "")
    mcp_api_key_access: bool = field(default_factory=lambda: _bool("MCP_API_KEY_ACCESS", False))
    quota_reserve_tokens: int = field(default_factory=lambda: _int("API_KEY_QUOTA_RESERVE", 1024, 0))
    provider_token_key: str = field(default_factory=lambda: _env("PROVIDER_TOKEN_KEY", "") or "")

    def __post_init__(self):
        if len(self.provider_token_previous_keys) > 5 or any(not isinstance(key, str) or len(key) < 16 for key in self.provider_token_previous_keys):
            raise ValueError("PROVIDER_TOKEN_PREVIOUS_KEYS must contain at most five previous keys")
        environment = (_env("APP_ENV", "development") or "development").lower()
        if environment == "production":
            if not self.session_secret or len(self.session_secret) < 32:
                raise ValueError("ADMIN_SESSION_SECRET must contain at least 32 characters in production")
            if not self.admin_token:
                raise ValueError("ADMIN_TOKEN is required in production")
            if not (self.admin_password_hash or self.bootstrap_password):
                raise ValueError("ADMIN_PASSWORD_HASH or ADMIN_PASSWORD is required in production")
            if not self.provider_token_key:
                raise ValueError("PROVIDER_TOKEN_KEY is required in production")


@dataclass(frozen=True)
class WorkerConfig:
    count: int = field(default_factory=lambda: _int("KB_WORKER_COUNT", 1, 1))
    lease_seconds: int = field(default_factory=lambda: _int("KB_TASK_LEASE_SECONDS", 300, 30))
    max_attempts: int = field(default_factory=lambda: _int("KB_TASK_MAX_ATTEMPTS", 3, 1))


@dataclass(frozen=True)
class AppConfig:
    quota_recovery_dir: str = field(default_factory=lambda: _env("QUOTA_RECOVERY_DIR", "data/quota-recovery") or "data/quota-recovery")
    server_port: int = field(default_factory=lambda: _int("SERVER_PORT", 9900, 1))
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    workers: WorkerConfig = field(default_factory=WorkerConfig)
    cors_allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in (_env("CORS_ALLOWED_ORIGINS", "http://localhost:9900") or "").split(",") if x.strip()))
    api_key_quota_reserve: int = field(default_factory=lambda: _int("API_KEY_QUOTA_RESERVE", 1024, 0))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "info") or "info")
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development") or "development")

    def __post_init__(self):
        if not self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin")


config = AppConfig()
