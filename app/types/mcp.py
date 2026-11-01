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


class DocumentArguments(EmptyArguments):
    kb_id: str = Field(min_length=1, max_length=128)
    doc_id: str = Field(min_length=1, max_length=128)


class KnowledgeBaseArguments(EmptyArguments):
    kb_id: str = Field(min_length=1, max_length=128)


class WikiProjectArguments(EmptyArguments):
    project_id: str = Field(min_length=1, max_length=128)


class WikiPageArguments(WikiProjectArguments):
    page_id: str = Field(min_length=1, max_length=128)


class WikiSearchArguments(WikiProjectArguments):
    query: str = Field(default="", max_length=512)
    tag: str | None = Field(default=None, max_length=64)


class WikiAskArguments(WikiProjectArguments):
    question: str = Field(min_length=1, max_length=32768)
    model: str = Field(min_length=1, max_length=128)
    top_k: int = Field(default=5, ge=1, le=20)


TOOL_ARGUMENTS = {
    "ask_knowledge_base": AskArguments,
    "search_knowledge_base": SearchArguments,
    "list_knowledge_bases": EmptyArguments,
    "get_knowledge_document": DocumentArguments,
    "list_knowledge_documents": KnowledgeBaseArguments,
    "reindex_knowledge_document": DocumentArguments,
    "list_wiki_projects": EmptyArguments,
    "list_wiki_pages": WikiSearchArguments,
    "get_wiki_page": WikiPageArguments,
    "get_wiki_tags": WikiProjectArguments,
    "get_wiki_graph": WikiProjectArguments,
    "ask_wiki": WikiAskArguments,
}
