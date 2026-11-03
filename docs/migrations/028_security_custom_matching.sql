-- Compatibility DDL adds match_type='regex' to legacy tables only.
UPDATE security_custom_rules SET rule_type='blacklist' WHERE rule_type IS NULL OR rule_type NOT IN ('blacklist','whitelist');
