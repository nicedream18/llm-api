"""Domain entities shared across modules."""
from dataclasses import dataclass, field


@dataclass
class ChannelEntity:
    id: str | None = None
    name: str = ""
    type: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    models: list = field(default_factory=list)
    status: int = 1
    priority: int = 0
    weight: int = 1
    config: dict | None = None
    model_mapping: dict | None = None
    last_test_at: str | None = None
    last_test_ok: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    api_keys: list["ChannelApiKeyEntity"] = field(default_factory=list)


@dataclass
class ChannelApiKeyEntity:
    id: str | None = None
    channel_id: str | None = None
    name: str = ""
    api_key: str = ""
    status: int = 1
    weight: int = 1
    last_error: str | None = None
    cooldown_until: str | None = None
    last_used_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ApiKeyEntity:
    id: str | None = None
    name: str = ""
    key: str | None = None
    status: int = 1
    allowed_models: list = field(default_factory=list)
    allowed_channels: list = field(default_factory=list)
    quota_limit: int = 0
    quota_used: int = 0
    expires_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class DispatchResult:
    channel: ChannelEntity
    upstream_model: str
    success: bool = True


@dataclass
class ProxyRequestEntity:
    model: str
    body: dict
    stream: bool = False
    api_key: str | None = None
    protocol_type: str = "openai"
    headers: dict = field(default_factory=dict)
    allowed_channels: frozenset[str] = frozenset()
    endpoint: str = "/v1/chat/completions"
    upstream_api_key: str | None = None


@dataclass
class ProxyResponseEntity:
    status_code: int = 200
    body: str = ""
    raw_body: bytes | None = None
    content_type: str | None = None
    success: bool = True
    error_message: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    channel_id: str | None = None
    channel_name: str | None = None
    upstream_model: str | None = None


@dataclass
class RequestLogEntity:
    id: str
    api_key_id: str | None = None
    api_key_name: str | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    model: str = ""
    upstream_model: str | None = None
    mode: str = "chat"
    protocol_type: str | None = None
    stream: bool = False
    retry: bool = False
    status_code: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    risk_level: str = "Clean"
    risk_score: int = 0
    risk_summary: str | None = None
    security_action: str = "Allow"
    sanitized: bool = False
    blocked_reason: str | None = None
    client_ip: str | None = None
    error_message: str | None = None
    request_body: str | None = None
    response_choices: str | None = None
    trace_id: str | None = None
    created_at: str | None = None
    seq: int | None = None
    request_id: str | None = None
    endpoint: str | None = None
    attempt_count: int = 1
    final_attempt: int = 1
    stream_status: str | None = None
    usage_source: str | None = None
    client_disconnect: bool = False
    truncated: bool = False


@dataclass
class LogStatsEntity:
    total_requests: int = 0
    total_tokens: int = 0
    total_errors: int = 0
    avg_duration_ms: float = 0
    active_channels: int = 0
    active_api_keys: int = 0


@dataclass
class ChannelStatsEntity:
    channel_id: str | None = None
    channel_name: str | None = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


@dataclass
class ApiKeyStatsEntity:
    api_key_id: str | None = None
    api_key_name: str | None = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


@dataclass
class SecurityFindingEntity:
    id: str
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


@dataclass
class SecurityScanResult:
    risk_level: str = "Clean"
    risk_score: int = 0
    summary: str = ""
    findings: list = field(default_factory=list)
    blocked: bool = False
    blocked_reason: str | None = None
    sanitized: bool = False
    sanitized_body: str | None = None


@dataclass
class SecurityBuiltinRuleEntity:
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


@dataclass
class SecurityCustomRuleEntity:
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


@dataclass
class KbKnowledgeBaseEntity:
    id: str | None = None
    name: str = ""
    description: str | None = None
    tags: list | None = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    status: int = 1
    embedding_model: str | None = None
    embedding_channel_id: str | None = None
    embedding_dim: int = 0
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    index_status: str = "none"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class KbDocumentEntity:
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


@dataclass
class KbChunkEntity:
    id: str | None = None
    doc_id: str | None = None
    kb_id: str | None = None
    content: str = ""
    chunk_index: int | None = None
    token_count: int | None = None
    embedding: bytes | None = None
    chunk_type: str | None = None
    language: str | None = None
    metadata: str | None = None
    created_at: str | None = None


@dataclass
class KbTaskEntity:
    id: str | None = None
    kb_id: str | None = None
    doc_id: str | None = None
    task_type: str = "import"
    status: str = "pending"
    progress: int = 0
    total_items: int = 0
    done_items: int = 0
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    payload: str | None = None
    worker_id: str | None = None
    lease_until: str | None = None
    attempt_count: int = 0
    started_at: str | None = None


@dataclass
class KbStatsEntity:
    kb_id: str | None = None
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    conversation_count: int = 0
    index_status: str = "none"
    last_doc_name: str | None = None
    last_doc_at: str | None = None


@dataclass
class SearchResultEntity:
    chunk_id: str | None = None
    doc_id: str | None = None
    filename: str | None = None
    content: str | None = None
    score: float = 0.0
    metadata: dict | None = None


@dataclass
class RagAnswerEntity:
    answer: str = ""
    sources: list = field(default_factory=list)
    usage: dict | None = None
    retrieval_details: list = field(default_factory=list)


@dataclass
class AgentConfigEntity:
    id: str | None = None
    agent_id: str | None = None
    name: str | None = None
    agent_name: str | None = None
    agent_desc: str | None = None
    app_name: str | None = None
    system_prompt: str | None = None
    description: str | None = None
    model: str | None = None
    config_json: str | None = None
    tools: list | None = None
    metadata: dict | None = None
    enabled: int | None = None
    status: int = 1
    created_at: str | None = None
    updated_at: str | None = None
