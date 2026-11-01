"""DTO definitions for API contracts."""
from pydantic import BaseModel, Field


class AdminLoginDTO(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class AdminSessionDTO(BaseModel):
    authenticated: bool
    username: str | None = None


class QuotaStatusDTO(BaseModel):
    api_key_id: str
    quota_limit: int | None = None
    quota_used: int = 0
    quota_remaining: int | None = None


class RouteAttemptDTO(BaseModel):
    attempt_no: int
    channel_id: str | None = None
    status_code: int | None = None
    error_type: str | None = None
    duration_ms: int = 0


class TaskCancelDTO(BaseModel):
    reason: str | None = None


class HealthDetailDTO(BaseModel):
    status: str
    checks: dict


class ChannelApiKeyDTO(BaseModel):
    id: str | None = None
    channel_id: str | None = None
    name: str = ""
    api_key: str | None = None
    status: int = 1
    weight: int = Field(default=1, ge=1, le=1000)
    last_error: str | None = None
    cooldown_until: str | None = None
    last_used_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ChannelDTO(BaseModel):
    id: str | None = None
    name: str = ""
    type: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] = Field(default_factory=list)
    status: int = 1
    priority: int = 0
    weight: int = 1
    config: dict | None = None
    model_mapping: dict | None = None
    last_test_at: str | None = None
    last_test_ok: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    api_keys: list["ChannelApiKeyDTO"] | None = None


class ApiKeyDTO(BaseModel):
    id: str | None = None
    name: str = ""
    key: str | None = None
    status: int = 1
    allowed_models: list[str] = Field(default_factory=list)
    allowed_channels: list[str] = Field(default_factory=list)
    quota_limit: int = 0
    quota_used: int = 0
    expires_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


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
    id: str | None = None
    seq: int | None = None
    api_key_id: str | None = None
    api_key_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    model: str | None = None
    upstream_model: str | None = None
    mode: str | None = None
    status_code: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    error_message: str | None = None
    is_stream: bool = False
    is_retry: bool = False
    request_body: str | None = None
    response_choices: str | None = None
    risk_level: str = "Clean"
    risk_score: int = 0
    risk_summary: str | None = None
    security_action: str = "Allow"
    sanitized: bool = False
    blocked_reason: str | None = None
    trace_id: str | None = None
    created_at: str | None = None


class ChannelStatsDTO(BaseModel):
    channel_id: str | None = None
    channel_name: str | None = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


class ApiKeyStatsDTO(BaseModel):
    api_key_id: str | None = None
    api_key_name: str | None = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


class CreateKbDTO(BaseModel):
    name: str
    description: str | None = None
    tags: list[str] | None = None
    chunk_size: int | None = 512
    chunk_overlap: int | None = 50
    embedding_model: str | None = None
    embedding_channel_id: str | None = None


class KbKnowledgeBaseDTO(BaseModel):
    id: str | None = None
    name: str = ""
    description: str | None = None
    tags: list[str] | None = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    status: int = 1
    index_status: str = "none"
    embedding_model: str | None = None
    embedding_channel_id: str | None = None
    embedding_dim: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class UploadDocDTO(BaseModel):
    filename: str
    content: str
    file_type: str | None = "txt"
    source_type: str | None = "file"


class KbDocumentDTO(BaseModel):
    id: str | None = None
    kb_id: str | None = None
    name: str = ""
    source_type: str | None = None
    source_path: str | None = None
    status: str | None = None
    chunk_count: int = 0
    total_tokens: int = 0
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class KbAskRequestDTO(BaseModel):
    kb_id: str | None = None
    question: str = ""
    model: str | None = None
    top_k: int | None = 5
    search_mode: str | None = "hybrid"
    vector_weight: float | None = 0.7
    keyword_weight: float | None = 0.3
    max_rounds: int | None = 3
    history: list[dict] | None = None


class KbAskResponseDTO(BaseModel):
    answer: str = ""
    sources: list[dict] = Field(default_factory=list)
    usage: dict | None = None
    retrieval_details: list[dict] = Field(default_factory=list)


class KbSearchRequestDTO(BaseModel):
    kb_id: str | None = None
    query: str = ""
    top_k: int | None = 5
    search_mode: str | None = "keyword"


class KbSearchResultDTO(BaseModel):
    chunk_id: str | None = None
    doc_id: str | None = None
    filename: str | None = None
    content: str | None = None
    score: float = 0.0
    metadata: dict | None = None


class KbStatsDTO(BaseModel):
    kb_id: str | None = None
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    conversation_count: int = 0
    index_status: str = "none"
    last_doc_name: str | None = None
    last_doc_at: str | None = None


class KbTagDTO(BaseModel):
    word: str
    count: int


class AgentConfigDTO(BaseModel):
    id: str | None = None
    agent_id: str | None = None
    agent_name: str = ""
    agent_desc: str | None = None
    app_name: str | None = None
    config_json: str | None = None
    status: int = 1
    created_at: str | None = None
    updated_at: str | None = None


class AgentChatRequestDTO(BaseModel):
    agent_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    message: str = ""


class AgentChatResponseDTO(BaseModel):
    session_id: str = ""
    response: str = ""
    author: str | None = None


class SecurityBuiltinRuleDTO(BaseModel):
    id: str | None = None
    category: str | None = None
    rule_id: str | None = None
    name: str | None = None
    description: str | None = None
    severity: str | None = None
    pattern: str | None = None
    action: str | None = None
    enabled: int = 1
    created_at: str | None = None
    updated_at: str | None = None


class SecurityCustomRuleDTO(BaseModel):
    id: str | None = None
    category: str | None = None
    name: str = ""
    description: str | None = None
    severity: str | None = None
    pattern: str | None = None
    action: str | None = None
    enabled: int = 1
    created_at: str | None = None
    updated_at: str | None = None


class SecurityFindingDTO(BaseModel):
    id: str | None = None
    log_id: str | None = None
    phase: str | None = None
    category: str | None = None
    rule_id: str | None = None
    severity: str | None = None
    title: str | None = None
    description: str | None = None
    location: str | None = None
    evidence_masked: str | None = None
    evidence_hash: str | None = None
    action: str | None = None
    created_at: str | None = None


class ImportSourceDTO(BaseModel):
    source_type: str = "git"
    repo_url: str | None = None
    branch: str | None = None
    token: str | None = None
    url: str | None = None
    dir_path: str | None = None
    excluded_dirs: list[str] = Field(default_factory=list)
    included_files: list[str] = Field(default_factory=list)
    max_file_size: int | None = None
