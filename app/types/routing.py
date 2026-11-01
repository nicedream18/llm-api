"""Validated route policy and credential-free preview input."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoutePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    strategy: Literal["weighted", "quota_balanced"] = "weighted"
    channels: list[str] = Field(default_factory=list, max_length=1000)
    api_key_ids: list[str] = Field(default_factory=list, max_length=1000)
    models: list[str] = Field(default_factory=list, max_length=1000)
    endpoints: list[str] = Field(default_factory=list, max_length=30)
    max_concurrent: int = Field(default=100, ge=1, le=1000)
    retry_budget: int = Field(default=2, ge=0, le=10)
    unknown_quota: Literal["allow", "deny"] = "allow"


class RoutePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=256)
    endpoint: str = Field(default="/v1/chat/completions", max_length=128)
    route_group: str = Field(default="", max_length=64, pattern=r"^[\w-]*$")
    principal_id: str | None = Field(default=None, max_length=64)
    allowed_channels: list[str] = Field(default_factory=list, max_length=1000)
