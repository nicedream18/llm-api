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


class CreateKnowledgeBaseArguments(EmptyArguments):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    tags: list[str] = Field(default_factory=list, max_length=64)
    chunk_size: int = Field(default=512, ge=64, le=8192)
    chunk_overlap: int = Field(default=50, ge=0, le=2048)
    embedding_model: str | None = Field(default=None, max_length=128)
    embedding_channel_id: str | None = Field(default=None, max_length=64)


class UpdateKnowledgeBaseArguments(CreateKnowledgeBaseArguments):
    kb_id: str = Field(min_length=1, max_length=128)


class UploadKnowledgeDocumentArguments(EmptyArguments):
    kb_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=16 * 1024 * 1024)
    file_type: str = Field(default="txt", min_length=1, max_length=32)
    source_type: str = Field(default="file", min_length=1, max_length=32)


class SourceArguments(KnowledgeBaseArguments):
    source_id: str = Field(min_length=1, max_length=128)


class CreateSourceArguments(KnowledgeBaseArguments):
    source_type: str = Field(default="file", min_length=1, max_length=32)
    source_url: str | None = Field(default=None, max_length=2048)
    source_path: str | None = Field(default=None, max_length=2048)
    filename: str | None = Field(default=None, max_length=512)
    content: str | None = Field(default=None, max_length=16 * 1024 * 1024)


class SoftwareToolArguments(EmptyArguments):
    tool_id: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict)
    approved: bool = False


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
    "create_knowledge_base": CreateKnowledgeBaseArguments,
    "update_knowledge_base": UpdateKnowledgeBaseArguments,
    "delete_knowledge_base": KnowledgeBaseArguments,
    "ask_knowledge_base": AskArguments,
    "search_knowledge_base": SearchArguments,
    "list_knowledge_bases": EmptyArguments,
    "upload_knowledge_document": UploadKnowledgeDocumentArguments,
    "get_knowledge_document": DocumentArguments,
    "list_knowledge_documents": KnowledgeBaseArguments,
    "delete_knowledge_document": DocumentArguments,
    "reindex_knowledge_document": DocumentArguments,
    "build_knowledge_index": KnowledgeBaseArguments,
    "drop_knowledge_index": KnowledgeBaseArguments,
    "list_knowledge_sources": KnowledgeBaseArguments,
    "create_knowledge_source": CreateSourceArguments,
    "delete_knowledge_source": SourceArguments,
    "list_wiki_projects": EmptyArguments,
    "list_wiki_pages": WikiSearchArguments,
    "get_wiki_page": WikiPageArguments,
    "get_wiki_tags": WikiProjectArguments,
    "get_wiki_graph": WikiProjectArguments,
    "ask_wiki": WikiAskArguments,
    "invoke_software_tool": SoftwareToolArguments,
}
