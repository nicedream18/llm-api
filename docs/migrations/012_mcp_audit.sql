-- Persistent, redacted MCP tool execution audit records.
CREATE TABLE IF NOT EXISTS mcp_audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    request_id VARCHAR(128) NULL,
    principal_type VARCHAR(16) NULL,
    principal_id VARCHAR(128) NULL,
    tool_name VARCHAR(128) NOT NULL,
    success TINYINT NOT NULL DEFAULT 0,
    error_type VARCHAR(64) NULL,
    duration_ms BIGINT NOT NULL DEFAULT 0,
    created_at VARCHAR(32) NOT NULL
);
CREATE INDEX idx_mcp_audit_created ON mcp_audit_logs (created_at);
CREATE INDEX idx_mcp_audit_principal ON mcp_audit_logs (principal_type, principal_id);
CREATE INDEX idx_mcp_audit_tool ON mcp_audit_logs (tool_name);
