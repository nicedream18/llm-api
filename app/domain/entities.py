"""Domain entities shared across modules."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChannelEntity:
    id: Optional[str] = None
    name: str = ""
    type: str = "openai"
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: list = field(default_factory=list)
    status: int = 1
    priority: int = 0
    weight: int = 1
    config: Optional[dict] = None
    model_mapping: Optional[dict] = None
    last_test_at: Optional[str] = None
    last_test_ok: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ApiKeyEntity:
    id: Optional[str] = None
    name: str = ""
    key: Optional[str] = None
    status: int = 1
    allowed_models: list = field(default_factory=list)
    allowed_channels: list = field(default_factory=list)
    quota_limit: int = 0
    quota_used: int = 0
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
    api_key: Optional[str] = None
    protocol_type: str = "openai"
    headers: dict = field(default_factory=dict)


@dataclass
class ProxyResponseEntity:
    status_code: int = 200
    body: str = ""
    success: bool = True
    error_message: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    upstream_model: Optional[str] = None


@dataclass
class RequestLogEntity:
    id: str
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    model: str = ""
    upstream_model: Optional[str] = None
    mode: str = "chat"
    protocol_type: Optional[str] = None
    stream: bool = False
    retry: bool = False
    status_code: Optional[int] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    risk_level: str = "Clean"
    risk_score: int = 0
    risk_summary: Optional[str] = None
    security_action: str = "Allow"
    sanitized: bool = False
    blocked_reason: Optional[str] = None
    client_ip: Optional[str] = None
    error_message: Optional[str] = None
    request_body: Optional[str] = None
    response_choices: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: Optional[str] = None
    seq: Optional[int] = None


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
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


@dataclass
class ApiKeyStatsEntity:
    api_key_id: Optional[str] = None
    api_key_name: Optional[str] = None
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0


@dataclass
class SecurityFindingEntity:
    id: str
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


@dataclass
class SecurityScanResult:
    risk_level: str = "Clean"
    risk_score: int = 0
    summary: str = ""
    findings: list = field(default_factory=list)
    blocked: bool = False
    blocked_reason: Optional[str] = None
    sanitized: bool = False


@dataclass
class SecurityBuiltinRuleEntity:
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


@dataclass
class SecurityCustomRuleEntity:
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


@dataclass
class KbKnowledgeBaseEntity:
    id: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    tags: Optional[list] = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    status: int = 1
    embedding_model: Optional[str] = None
    embedding_channel_id: Optional[str] = None
    embedding_dim: int = 0
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    index_status: str = "none"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class KbDocumentEntity:
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


@dataclass
class KbChunkEntity:
    id: Optional[str] = None
    doc_id: Optional[str] = None
    kb_id: Optional[str] = None
    content: str = ""
    chunk_index: Optional[int] = None
    token_count: Optional[int] = None
    embedding: Optional[bytes] = None
    chunk_type: Optional[str] = None
    language: Optional[str] = None
    metadata: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class KbTaskEntity:
    id: Optional[str] = None
    kb_id: Optional[str] = None
    doc_id: Optional[str] = None
    task_type: str = "import"
    status: str = "pending"
    progress: int = 0
    total_items: int = 0
    done_items: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class KbStatsEntity:
    kb_id: Optional[str] = None
    doc_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0
    conversation_count: int = 0
    index_status: str = "none"
    last_doc_name: Optional[str] = None
    last_doc_at: Optional[str] = None


@dataclass
class SearchResultEntity:
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    filename: Optional[str] = None
    content: Optional[str] = None
    score: float = 0.0
    metadata: Optional[dict] = None


@dataclass
class RagAnswerEntity:
    answer: str = ""
    sources: list = field(default_factory=list)
    usage: Optional[dict] = None
    retrieval_details: list = field(default_factory=list)


@dataclass
class AgentConfigEntity:
    id: Optional[str] = None
    agent_id: Optional[str] = None
    name: Optional[str] = None
    agent_name: Optional[str] = None
    agent_desc: Optional[str] = None
    app_name: Optional[str] = None
    system_prompt: Optional[str] = None
    description: Optional[str] = None
    model: Optional[str] = None
    config_json: Optional[str] = None
    tools: Optional[list] = None
    metadata: Optional[dict] = None
    enabled: Optional[int] = None
    status: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
