CREATE TABLE IF NOT EXISTS provider_auth_runtime (
    account_id VARCHAR(64) PRIMARY KEY,
    generation BIGINT NOT NULL DEFAULT 0,
    refresh_owner VARCHAR(64) NULL,
    refresh_until VARCHAR(32) NULL,
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_oauth_states (
    state_hash VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    principal_type VARCHAR(32) NOT NULL,
    principal_id VARCHAR(128) NOT NULL,
    verifier TEXT NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    generation BIGINT NOT NULL,
    expires_at VARCHAR(32) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_provider_oauth_expiry ON provider_oauth_states (expires_at);
