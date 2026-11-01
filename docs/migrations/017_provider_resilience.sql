ALTER TABLE provider_accounts ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE provider_accounts ADD COLUMN cooldown_until VARCHAR(32) NULL;
CREATE INDEX idx_provider_cooldown ON provider_accounts (cooldown_until);
