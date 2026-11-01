"""Authentication context shared by middleware and application services."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AuthContext:
    principal_type: Literal["admin", "api_key", "mcp"]
    principal_id: str
    principal_name: str | None = None
    allowed_models: frozenset[str] = frozenset()
    allowed_channels: frozenset[str] = frozenset()
    quota_limit: int | None = None
    quota_used: int = 0
    raw_key_fingerprint: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.principal_type == "admin"

    @property
    def is_api_key(self) -> bool:
        return self.principal_type == "api_key"

    @property
    def is_mcp(self) -> bool:
        return self.principal_type == "mcp"
