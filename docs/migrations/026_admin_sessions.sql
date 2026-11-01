CREATE TABLE IF NOT EXISTS admin_sessions (
    id VARCHAR(64) PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    username VARCHAR(128) NOT NULL,
    credential_hash VARCHAR(64) NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    revoked_at BIGINT
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_subject ON admin_sessions(username, expires_at);
CREATE TABLE IF NOT EXISTS admin_login_windows (
    subject_hash VARCHAR(64) PRIMARY KEY,
    window_start BIGINT NOT NULL,
    attempts INT NOT NULL
);
