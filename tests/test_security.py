from app.config import SecuritySettings
from app.domain.security import SecurityScanner


def test_redaction_returns_safe_body():
    scanner = SecurityScanner()
    settings = SecuritySettings(mode='redact', redact_secrets=True)
    raw = '{"messages":[{"content":"sk-123456789012345678901234"}]}'
    result = scanner.scan(raw, 'request', settings)
    assert result.sanitized
    assert '[REDACTED]' in result.sanitized_body
    assert 'sk-123456789012345678901234' not in result.sanitized_body
