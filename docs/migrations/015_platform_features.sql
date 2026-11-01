CREATE TABLE IF NOT EXISTS prompt_templates (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL,
    template TEXT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    enabled TINYINT NOT NULL DEFAULT 1,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_cache (
    id VARCHAR(64) PRIMARY KEY,
    cache_key VARCHAR(128) NOT NULL UNIQUE,
    model VARCHAR(128) NOT NULL,
    scope VARCHAR(128) NOT NULL,
    request TEXT NOT NULL,
    response TEXT NOT NULL,
    expires_at VARCHAR(32) NOT NULL,
    created_at VARCHAR(32) NOT NULL
);
CREATE INDEX semantic_cache_expiry ON semantic_cache (expires_at);
