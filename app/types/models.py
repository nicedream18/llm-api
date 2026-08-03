"""DTO definitions for API contracts."""
from typing import Any, Optional
from pydantic import BaseModel


class ChannelDTO(BaseModel):
    id: Optional[str] = None
    name: str = ""
    type: str = "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: list[str] = []
    status: int = 1
    priority: int = 0
    weight: int = 1
    config: Optional[dict] = None
    model_mapping: Optional[dict] = None
    last_test_at: Optional[str] = None
    last_test_ok: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApiKeyDTO(BaseModel):
    id: Optional[str] = None
    name: str = ""
    key: Optional[str] = None
    status: int = 1
    allowed_models: list[str] = []
    allowed_channels: list[str] = []
    quota_limit: int = 0
    quota_used: int = 0
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TestChannelResultDTO(BaseModel):
    channel_id: str
    success: bool
    message: str = ""
    duration_ms: int = 0


class DashboardStatsDTO(BaseModel):
    total_requests: int = 0
    total_tokens: int = 0
    total_errors: int = 0
    avg_duration_ms: float = 0
    active_channels: int = 0
    active_api_keys: int = 0
    health_score: int = 100
    health_badge: str = "excellent"


class RequestLogDTO(BaseModel):
    id: Optional[str] = None
    seq: Optional[int] = None
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    model: Optional[str] = None
    upstream_model: Optional[str] = None
    mode: Optional[str] = None
    status_code: Optional[int] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error_message: Optional[str] = None
    is_stream: bool = False
    is_retry: bool = False
    request_body: Optional[str] = None
    response_choices: Optional[str] = None
    risk_level: str = "Clean"
    risk_score: int = 0
    risk_summary: Optional[str] = None
    security_action: str = "Allow"
    sanitized: bool = False
    blocked_reason: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: Optional[str] = None


class ChannelStatsDTO(BaseModel):
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


class ApiKeyStatsDTO(BaseModel):
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


class CreateKbDTO(BaseModel):
    name: str
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    chunk_size: Optional[int] = 512
    chunk_overlap: Optional[int] = 50
    embedding_model: Optional[str] = None
    embedding_channel_id: Optional[str] = None


class KbKnowledgeBaseDTO(BaseModel):
    id: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    status: int = 1
    index_status: str = "none"
    embedding_model: Optional[str] = None
    embedding_channel_id: Optional[str] = None
    embedding_dim: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UploadDocDTO(BaseModel):
    filename: str
    content: str
    file_type: Optional[str] = "txt"
    source_type: Optional[str] = "file"


class KbDocumentDTO(BaseModel):
    id: Optional[str] = None
    kb_id: Optional[str] = None
    name: str = ""
    source_type: Optional[str] = None
    source_path: Optional[str] = None
    status: Optional[str] = None
    chunk_count: int = 0
    total_tokens: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KbAskRequestDTO(BaseModel):
    kb_id: Optional[str] = None
    question: str = ""
    model: Optional[str] = None
    top_k: Optional[int] = 5
    search_mode: Optional[str] = "hybrid"
    vector_weight: Optional[float] = 0.7
    keyword_weight: Optional[float] = 0.3
    max_rounds: Optional[int] = 3
    history: Optional[list[dict]] = None


class KbAskResponseDTO(BaseModel):
    answer: str = ""
    sources: list[dict] = []
    usage: Optional[dict] = None
    retrieval_details: list[dict] = []


class KbSearchRequestDTO(BaseModel):
    kb_id: Optional[str] = None
    query: str = ""
    top_k: Optional[int] = 5
    search_mode: Optional[str] = "keyword"


class KbSearchResultDTO(BaseModel):
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    filename: Optional[str] = None
    content: Optional[str] = None
    score: float = 0.0
    metadata: Optional[dict] = None


class KbStatsDTO(BaseModel):
    kb_id: Optional[str] = None
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    conversation_count: int = 0
    index_status: str = "none"
    last_doc_name: Optional[str] = None
    last_doc_at: Optional[str] = None


class KbTagDTO(BaseModel):
    word: str
    count: int


class AgentConfigDTO(BaseModel):
    id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: str = ""
    agent_desc: Optional[str] = None
    app_name: Optional[str] = None
    config_json: Optional[str] = None
    status: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentChatRequestDTO(BaseModel):
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str = ""


class AgentChatResponseDTO(BaseModel):
    session_id: str = ""
    response: str = ""
    author: Optional[str] = None


class SecurityBuiltinRuleDTO(BaseModel):
    id: Optional[str] = None
    category: Optional[str] = None
    rule_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    pattern: Optional[str] = None
    action: Optional[str] = None
    enabled: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SecurityCustomRuleDTO(BaseModel):
    id: Optional[str] = None
    category: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    severity: Optional[str] = None
    pattern: Optional[str] = None
    action: Optional[str] = None
    enabled: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SecurityFindingDTO(BaseModel):
    id: Optional[str] = None
    log_id: Optional[str] = None
    phase: Optional[str] = None
    category: Optional[str] = None
    rule_id: Optional[str] = None
    severity: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    evidence_masked: Optional[str] = None
    evidence_hash: Optional[str] = None
    action: Optional[str] = None
    created_at: Optional[str] = None


class ImportSourceDTO(BaseModel):
    source_type: str = "git"
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    token: Optional[str] = None
    url: Optional[str] = None
    dir_path: Optional[str] = None
    excluded_dirs: list[str] = []
    included_files: list[str] = []
    max_file_size: Optional[int] = None
