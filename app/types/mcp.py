"""Validated arguments shared by the MCP and legacy tool endpoints."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchArguments(EmptyArguments):
    kb_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=32768)
    top_k: int = Field(default=5, ge=1, le=100)
    search_mode: Literal["keyword", "vector", "hybrid"] = "keyword"


class AskArguments(EmptyArguments):
    kb_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=32768)
    top_k: int = Field(default=5, ge=1, le=100)
    search_mode: Literal["keyword", "vector", "hybrid"] = "hybrid"


TOOL_ARGUMENTS = {
    "ask_knowledge_base": AskArguments,
    "search_knowledge_base": SearchArguments,
    "list_knowledge_bases": EmptyArguments,
}
