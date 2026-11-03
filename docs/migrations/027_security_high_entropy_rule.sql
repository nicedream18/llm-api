-- Register the generic high-entropy credential candidate detector in the admin rule list.
INSERT INTO security_builtin_rules
    (id, rule_id, category, severity, title, name, description, pattern, action, enabled, created_at, updated_at)
SELECT
    'builtin-credential-high-entropy',
    'credential_high_entropy',
    'credentials',
    'medium',
    'High-Entropy Credential Candidate',
    '高熵密钥候选',
    'Reports standalone ASCII tokens of at least 20 characters with Shannon entropy above 4.5 bits per character. This is a review signal, not proof of a secret.',
    NULL,
    'warn',
    1,
    UTC_TIMESTAMP(),
    UTC_TIMESTAMP()
WHERE NOT EXISTS (
    SELECT 1 FROM security_builtin_rules WHERE rule_id = 'credential_high_entropy'
);
