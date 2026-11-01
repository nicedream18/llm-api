"""Auth provider account contracts."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROVIDER_NAMES = ("codex", "gemini", "grok", "kimi", "qoder", "workbuddy")


class ProviderAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["codex", "gemini", "grok", "kimi", "qoder", "workbuddy"]
    name: str = Field(min_length=1, max_length=128)
    client_config: dict = Field(default_factory=dict)
    model_mapping: dict[str, str] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-1000, le=1000)


class ProviderTokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str = Field(min_length=1, max_length=16384)
    refresh_token: str | None = Field(default=None, max_length=16384)
    expires_at: str | None = Field(default=None, max_length=64)

    @field_validator("expires_at", mode="before")
    @classmethod
    def normalize_expiry(cls, value):
        if value is None:
            return None
        try:
            try:
                parsed = datetime.fromtimestamp(float(value), UTC)
            except ValueError:
                parsed = datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC).isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            raise ValueError("Invalid token expiry timestamp") from None


class ProviderAccountView(BaseModel):
    id: str
    provider: str
    name: str
    status: str
    priority: int = 0
    model_mapping: dict[str, str] = Field(default_factory=dict)
    quota: dict | None = None
    models: list[str] = Field(default_factory=list)
    failure_count: int = 0
    cooldown_until: str | None = None


class ProviderAccountQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str = Field(default="", max_length=128)
    provider: Literal["codex", "gemini", "grok", "kimi", "qoder", "workbuddy"] | None = None
    status: Literal["pending", "active", "signed_out"] | None = None
    group_name: str | None = Field(default=None, max_length=128)
    tag: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    archived: bool = False
    sort: Literal["priority", "name", "provider", "created_at"] = "priority"
    descending: bool = True
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=25, ge=1, le=100)


class ProviderOperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["enabled", "group_name", "tags", "archive", "restore"]
    enabled: bool = False
    group_name: str = Field(default="", max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=32)

    def value(self):
        if self.operation == "tags":
            tags = list(dict.fromkeys(item.strip() for item in self.tags if item.strip()))
            if any(len(item) > 64 for item in tags):
                raise ValueError("Tags must not exceed 64 characters")
            return tags
        return getattr(self, self.operation, None)


class ProviderBulkInput(ProviderOperationInput):
    account_ids: list[str] = Field(min_length=1, max_length=100)
