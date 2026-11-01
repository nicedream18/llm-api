CREATE TABLE IF NOT EXISTS route_groups (
    id VARCHAR(64) PRIMARY KEY,
    policy TEXT NOT NULL,
    updated_at VARCHAR(40) NOT NULL
);
CREATE TABLE IF NOT EXISTS route_runtime (
    resource_id VARCHAR(191) PRIMARY KEY,
    generation INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    cooldown_until VARCHAR(40),
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS route_leases (
    id VARCHAR(64) PRIMARY KEY,
    resource_id VARCHAR(191) NOT NULL,
    generation INTEGER NOT NULL,
    expires_at VARCHAR(40) NOT NULL,
    FOREIGN KEY (resource_id) REFERENCES route_runtime(resource_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_route_leases_resource ON route_leases(resource_id, expires_at);
