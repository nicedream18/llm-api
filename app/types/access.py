"""Explicit grants for data-plane and MCP principals."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AccessGrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_type: Literal["api_key", "mcp"]
    principal_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    resource_type: Literal["kb", "wiki", "software", "mcp_tool"]
    resource_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.*-]+$"
    )
    action: Literal["read", "write", "execute"]
