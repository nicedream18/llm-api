-- Non-admin access is explicit and tied to a stable principal ID.
CREATE TABLE IF NOT EXISTS access_grants (
    id VARCHAR(64) PRIMARY KEY,
    principal_type VARCHAR(16) NOT NULL,
    principal_id VARCHAR(64) NOT NULL,
    resource_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    action VARCHAR(16) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    UNIQUE (principal_type, principal_id, resource_type, resource_id, action)
);
