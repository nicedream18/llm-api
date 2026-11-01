-- Optional approval expiry metadata. Kept separate for idempotent upgrades.
CREATE TABLE IF NOT EXISTS software_approval_expiry (
    approval_id VARCHAR(64) PRIMARY KEY,
    expires_at VARCHAR(32) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    CONSTRAINT fk_software_approval_expiry_request
        FOREIGN KEY (approval_id) REFERENCES software_approval_requests(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_software_approval_expiry ON software_approval_expiry (expires_at);
