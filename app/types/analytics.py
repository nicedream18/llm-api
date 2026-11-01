"""Bounded analytics queries with explicit timezone and half-open UTC ranges."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AnalyticsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime | None = None
    end: datetime | None = None
    timezone: str = Field(default="UTC", max_length=64)
    group_by: Literal["day", "hour", "provider", "account_id", "model", "api_key_id", "route_group", "endpoint"] = "day"
    bucket: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    api_key_id: str | None = Field(default=None, max_length=64)
    route_group: str | None = Field(default=None, max_length=64)
    endpoint: str | None = Field(default=None, max_length=128)

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Analytics timestamps require a timezone")
        return value.astimezone(UTC) if value else None

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value

    @model_validator(mode="after")
    def bounds(self):
        self.end = self.end or datetime.now(UTC)
        self.start = self.start or self.end - timedelta(days=7)
        if self.start >= self.end or self.end - self.start > timedelta(days=93):
            raise ValueError("Analytics range must be positive and at most 93 days")
        if self.bucket:
            try:
                datetime.strptime(self.bucket, "%Y-%m-%d" if self.group_by == "day" else "%Y-%m-%dT%H:00%z")
            except ValueError:
                raise ValueError("Invalid analytics time bucket") from None
            if self.group_by not in {"day", "hour"}:
                raise ValueError("Time bucket requires day or hour grouping")
        return self


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    metric: Literal["failure_rate", "latency_p95", "unknown_price"]
    threshold: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    min_samples: int = Field(default=20, ge=1, le=100_000)
    window_minutes: int = Field(default=10, ge=1, le=60)
    severity: Literal["warning", "critical"] = "warning"
