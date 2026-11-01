"""Software connector and tool API contracts."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SoftwareInstanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    connector_type: Literal["cli", "http", "mcp", "openapi", "wechat", "clihub"]
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SoftwareToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str = Field(default="", max_length=4096)
    input_schema: dict = Field(default_factory=lambda: {"type": "object"})
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    approval_mode: Literal["none", "per_call", "always"] = "per_call"
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class SoftwareInvokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict = Field(default_factory=dict)
    approved: bool = False


class SoftwareApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    arguments: dict = Field(default_factory=dict)


class SoftwareApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool


class OpenApiPreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict[str, Any]


class OpenApiImportInput(OpenApiPreviewInput):
    name: str = Field(min_length=1, max_length=128)
    tools: list[str] | None = None
