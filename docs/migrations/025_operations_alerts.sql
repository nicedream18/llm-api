CREATE TABLE IF NOT EXISTS alert_rules (
    id VARCHAR(64) PRIMARY KEY,
    policy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_runtime (
    fingerprint VARCHAR(191) PRIMARY KEY,
    active_id VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS operational_alerts (
    id VARCHAR(64) PRIMARY KEY,
    fingerprint VARCHAR(191) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    message VARCHAR(512) NOT NULL,
    status VARCHAR(16) NOT NULL,
    opened_at VARCHAR(40) NOT NULL,
    last_seen_at VARCHAR(40) NOT NULL,
    resolved_at VARCHAR(40)
);
CREATE TABLE IF NOT EXISTS alert_events (
    id VARCHAR(64) PRIMARY KEY,
    alert_id VARCHAR(64) NOT NULL,
    action VARCHAR(16) NOT NULL,
    principal VARCHAR(128) NOT NULL,
    created_at VARCHAR(40) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON operational_alerts(status,last_seen_at);
