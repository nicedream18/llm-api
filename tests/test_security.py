from app.config import SecuritySettings
from app.domain.security import ENTROPY_RULE_ID, SecurityScanner


def test_redaction_returns_safe_body():
    scanner = SecurityScanner()
    settings = SecuritySettings(mode='redact', redact_secrets=True)
    raw = '{"messages":[{"content":"sk-123456789012345678901234"}]}'
    result = scanner.scan(raw, 'request', settings)
    assert result.sanitized
    assert '[REDACTED]' in result.sanitized_body
    assert 'sk-123456789012345678901234' not in result.sanitized_body


def test_high_entropy_token_is_reported_as_medium_warn_finding():
    scanner = SecurityScanner()
    token = "aB3dE5fG7hJ9kL2mN4pQ6rS"

    result = scanner.scan('{"token":"' + token + '"}', 'request', SecuritySettings())

    entropy_findings = [finding for finding in result.findings if finding.rule_id == ENTROPY_RULE_ID]
    assert len(entropy_findings) == 1
    assert entropy_findings[0].severity == "medium"
    assert entropy_findings[0].action == "warn"
    assert entropy_findings[0].location == "$.token"
    assert not result.blocked


def test_entropy_rule_ignores_low_entropy_and_known_prefix_tokens():
    scanner = SecurityScanner()
    low_entropy = "a" * 24
    known_key = "sk-" + "aB3dE5fG7hJ9kL2mN4pQ6rS"

    low_result = scanner.scan('{"value":"' + low_entropy + '"}', 'request', SecuritySettings())
    known_result = scanner.scan('{"value":"' + known_key + '"}', 'request', SecuritySettings())

    assert all(finding.rule_id != ENTROPY_RULE_ID for finding in low_result.findings)
    assert [finding.rule_id for finding in known_result.findings].count(ENTROPY_RULE_ID) == 0
    assert any(finding.rule_id == "credential_apikey_openai" for finding in known_result.findings)


def test_entropy_rule_can_be_disabled_by_builtin_override():
    from types import SimpleNamespace

    scanner = SecurityScanner()
    token = "aB3dE5fG7hJ9kL2mN4pQ6rS"
    result = scanner.scan(
        '{"token":"' + token + '"}',
        'request',
        SecuritySettings(),
        builtin_rules=[SimpleNamespace(rule_id=ENTROPY_RULE_ID, enabled=0)],
    )

    assert all(finding.rule_id != ENTROPY_RULE_ID for finding in result.findings)
