"""Normalized quota windows and durable synchronization inputs."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuotaWindow(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    window: str = Field(default="default", max_length=128)
    unit: Literal["tokens", "requests", "currency", "credits", "unknown"] = "unknown"
    remaining: Decimal | None = None
    limit: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    reset_at: str | None = Field(default=None, max_length=64)


def _default_kinds() -> list[Literal["quota", "models"]]:
    return ["quota", "models"]


class ProviderSyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kinds: list[Literal["quota", "models"]] = Field(default_factory=_default_kinds, min_length=1, max_length=2)


class ProviderSyncSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    quota_interval: int = Field(default=300, ge=60, le=86400)
    models_interval: int = Field(default=21600, ge=300, le=604800)
