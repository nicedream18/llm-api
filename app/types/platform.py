"""Prompt, semantic cache and client configuration contracts."""

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    template: str = Field(min_length=1, max_length=1_000_000)
    description: str = Field(default="", max_length=4096)
    enabled: bool = True


class PromptRenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variables: dict[str, str] = Field(default_factory=dict)


class CacheLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=128)
    request: dict
    scope: str = Field(default="default", min_length=1, max_length=128)


class CacheStoreInput(CacheLookupInput):
    response: dict
    ttl_seconds: int = Field(default=3600, ge=1, le=31_536_000)


class AppConfigWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    values: dict
