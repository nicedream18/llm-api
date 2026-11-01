CREATE TABLE IF NOT EXISTS provider_account_profiles (
    account_id VARCHAR(64) PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    group_name VARCHAR(128) NOT NULL DEFAULT '',
    tags TEXT NOT NULL,
    archived_at VARCHAR(32) NULL,
    FOREIGN KEY (account_id) REFERENCES provider_accounts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_provider_profile_group ON provider_account_profiles (group_name, enabled);
CREATE TABLE IF NOT EXISTS provider_account_events (
    id VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    details TEXT NOT NULL,
    created_at VARCHAR(32) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_events_account ON provider_account_events (account_id, created_at);
