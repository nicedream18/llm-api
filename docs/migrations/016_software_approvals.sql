CREATE TABLE IF NOT EXISTS software_approval_requests (
    id VARCHAR(64) PRIMARY KEY,
    tool_id VARCHAR(64) NOT NULL,
    principal_type VARCHAR(16) NULL,
    principal_id VARCHAR(128) NULL,
    arguments TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    decision_by VARCHAR(128) NULL,
    decision_at VARCHAR(32) NULL,
    error_type VARCHAR(64) NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_software_approval_status ON software_approval_requests (status, created_at);
