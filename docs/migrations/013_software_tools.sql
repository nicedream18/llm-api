CREATE TABLE IF NOT EXISTS software_instances (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    connector_type VARCHAR(32) NOT NULL,
    config TEXT NOT NULL,
    enabled TINYINT NOT NULL DEFAULT 1,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL
);
CREATE TABLE IF NOT EXISTS software_tools (
    id VARCHAR(64) PRIMARY KEY,
    instance_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    input_schema TEXT NOT NULL,
    risk_level VARCHAR(16) NOT NULL,
    approval_mode VARCHAR(16) NOT NULL,
    config TEXT NOT NULL,
    enabled TINYINT NOT NULL DEFAULT 1,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE (instance_id, name)
);
CREATE TABLE IF NOT EXISTS software_call_logs (
    id VARCHAR(64) PRIMARY KEY,
    tool_id VARCHAR(64) NOT NULL,
    principal_type VARCHAR(16) NULL,
    principal_id VARCHAR(128) NULL,
    status VARCHAR(16) NOT NULL,
    error_type VARCHAR(64) NULL,
    duration_ms BIGINT NOT NULL DEFAULT 0,
    request_summary TEXT NULL,
    response_summary TEXT NULL,
    created_at VARCHAR(32) NOT NULL
);
CREATE INDEX idx_software_calls_created ON software_call_logs (created_at);
