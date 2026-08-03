"""Application configuration loaded from environment."""
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class DatabaseConfig:
    host: str = os.getenv("DB_HOST", "192.168.1.108")
    port: int = int(os.getenv("DB_PORT", "13306"))
    name: str = os.getenv("DB_NAME", "waliapi")
    user: str = os.getenv("DB_USER", "root")
    password: str = os.getenv("DB_PASSWORD", "123456")
    pool_size: int = int(os.getenv("DB_POOL_SIZE", "15"))
    max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))

    @property
    def url(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
            "?charset=utf8mb4"
        )


@dataclass
class SecuritySettings:
    enabled: bool = os.getenv("SECURITY_ENABLED", "true").lower() == "true"
    mode: str = os.getenv("SECURITY_MODE", "audit")
    scan_unicode: bool = os.getenv("SCAN_UNICODE", "true").lower() == "true"
    scan_tools: bool = os.getenv("SCAN_TOOLS", "true").lower() == "true"
    scan_network: bool = os.getenv("SCAN_NETWORK", "true").lower() == "true"
    scan_response: bool = os.getenv("SCAN_RESPONSE", "false").lower() == "true"
    redact_secrets: bool = os.getenv("REDACT_SECRETS", "true").lower() == "true"
    block_on_critical: bool = os.getenv("BLOCK_ON_CRITICAL", "true").lower() == "true"


@dataclass
class GatewayConfig:
    retry_times: int = int(os.getenv("GATEWAY_RETRY_TIMES", "2"))


@dataclass
class AppConfig:
    server_port: int = int(os.getenv("SERVER_PORT", "9900"))
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    log_level: str = os.getenv("LOG_LEVEL", "info")


config = AppConfig()
