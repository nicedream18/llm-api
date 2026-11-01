-- Persistent MCP sessions and replayable notification events.
CREATE TABLE IF NOT EXISTS mcp_sessions (
    id VARCHAR(128) PRIMARY KEY,
    principal_type VARCHAR(16) NULL,
    principal_id VARCHAR(128) NULL,
    expires_at VARCHAR(64) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_sessions_expiry ON mcp_sessions (expires_at);

CREATE TABLE IF NOT EXISTS mcp_session_events (
    session_id VARCHAR(128) NOT NULL,
    event_id BIGINT NOT NULL,
    payload TEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (session_id, event_id),
    CONSTRAINT fk_mcp_session_events_session
        FOREIGN KEY (session_id) REFERENCES mcp_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mcp_session_events_created ON mcp_session_events (session_id, created_at);
