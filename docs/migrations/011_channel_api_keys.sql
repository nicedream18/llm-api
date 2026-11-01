-- Multiple independently routable upstream credentials per channel.
CREATE TABLE IF NOT EXISTS channel_api_keys (
    id VARCHAR(64) PRIMARY KEY,
    channel_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    api_key VARCHAR(512) NOT NULL,
    status TINYINT NOT NULL DEFAULT 1,
    weight INT NOT NULL DEFAULT 1,
    last_error TEXT NULL,
    cooldown_until VARCHAR(32) NULL,
    last_used_at VARCHAR(32) NULL,
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE (channel_id, api_key),
    KEY idx_channel_api_keys_channel (channel_id),
    CONSTRAINT fk_channel_api_keys_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
