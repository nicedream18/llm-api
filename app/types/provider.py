"""Auth provider account contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
