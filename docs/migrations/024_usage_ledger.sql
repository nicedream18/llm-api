CREATE TABLE IF NOT EXISTS price_versions (
    id VARCHAR(64) PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    model VARCHAR(256) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    input_per_million VARCHAR(64) NOT NULL,
    output_per_million VARCHAR(64) NOT NULL,
    effective_at VARCHAR(40) NOT NULL,
    created_at VARCHAR(40) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_lookup ON price_versions(provider, model, effective_at);
CREATE TABLE IF NOT EXISTS usage_ledger (
    id VARCHAR(64) PRIMARY KEY,
    execution_id VARCHAR(64) NOT NULL,
    event_key VARCHAR(40) NOT NULL,
    request_id VARCHAR(128) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    api_key_id VARCHAR(64),
    channel_id VARCHAR(128),
    provider VARCHAR(64),
    account_id VARCHAR(64),
    model VARCHAR(256) NOT NULL,
    route_group VARCHAR(64) NOT NULL,
    endpoint VARCHAR(128) NOT NULL,
    status_code INTEGER,
    outcome VARCHAR(32) NOT NULL,
    input_tokens BIGINT,
    output_tokens BIGINT,
    total_tokens BIGINT,
    usage_source VARCHAR(16) NOT NULL,
    duration_ms BIGINT NOT NULL,
    first_token_ms BIGINT,
    price_version VARCHAR(64),
    currency VARCHAR(3),
    cost VARCHAR(64),
    pricing_status VARCHAR(32) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    occurred_at VARCHAR(40) NOT NULL,
    UNIQUE (execution_id,event_key)
);
CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_ledger(occurred_at,kind);
CREATE INDEX IF NOT EXISTS idx_usage_request ON usage_ledger(request_id);
CREATE INDEX IF NOT EXISTS idx_usage_account ON usage_ledger(account_id,occurred_at);
