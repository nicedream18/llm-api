"""Usage facts and immutable price input. Rates are currency per million tokens."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=256)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    input_per_million: Decimal = Field(ge=0, max_digits=24, decimal_places=12, allow_inf_nan=False)
    output_per_million: Decimal = Field(ge=0, max_digits=24, decimal_places=12, allow_inf_nan=False)
    effective_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("effective_at")
    @classmethod
    def utc_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Price timestamps require a timezone")
        return value.astimezone(UTC)


class UsageFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: str = Field(min_length=1, max_length=64)
    event_key: str = Field(min_length=1, max_length=40)
    request_id: str = Field(min_length=1, max_length=128)
    kind: Literal["attempt", "outcome"]
    api_key_id: str | None = None
    channel_id: str | None = None
    provider: str | None = None
    account_id: str | None = None
    model: str
    route_group: str = ""
    endpoint: str
    status_code: int | None = None
    outcome: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_source: Literal["reported", "estimated", "unknown"] = "unknown"
    duration_ms: int = Field(default=0, ge=0)
    first_token_ms: int | None = Field(default=None, ge=0)
    occurred_at: str
