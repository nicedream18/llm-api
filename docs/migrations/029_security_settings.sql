CREATE TABLE IF NOT EXISTS security_settings (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    settings TEXT NOT NULL,
    updated_at VARCHAR(32) NOT NULL
);
