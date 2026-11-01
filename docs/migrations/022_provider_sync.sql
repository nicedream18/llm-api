CREATE TABLE IF NOT EXISTS provider_snapshots (
    account_id VARCHAR(64) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    generation BIGINT NOT NULL,
    payload TEXT NULL,
    fetched_at VARCHAR(32) NULL,
    last_attempt_at VARCHAR(32) NOT NULL,
    error_code VARCHAR(64) NULL,
    PRIMARY KEY (account_id,kind),
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_sync_settings (
    account_id VARCHAR(64) PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    quota_interval INTEGER NOT NULL DEFAULT 300,
    models_interval INTEGER NOT NULL DEFAULT 21600,
    next_quota_at VARCHAR(32) NOT NULL,
    next_models_at VARCHAR(32) NOT NULL,
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_sync_jobs (
    id VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at VARCHAR(32) NOT NULL,
    lease_owner VARCHAR(64) NULL,
    lease_until VARCHAR(32) NULL,
    error_code VARCHAR(64) NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE (account_id,kind),
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_provider_jobs_available ON provider_sync_jobs (status,available_at);
