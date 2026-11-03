import json

import pytest

from app.config import SecuritySettings
from app.domain.entities import SecurityCustomRuleEntity
from app.domain.security import SecurityScanner
from app.domain.security_redaction import SecurityLimitError, redact_body, redact_string


@pytest.mark.parametrize("secret", [
    "sk-proj-abcdefghijklmnopqrstuv_0123456789", "sk-ant-abcdefghijklmnopqrstuv-123456789",
    "AKIAABCDEFGHIJKLMNOP", "LTAIabcdefghijklmnop", "AKIDabcdefghijklmnopqrst",
    "ghp_" + "a" * 36, "AIza" + "b" * 35, "key-" + "a" * 24,
    "xoxb-123-abcd", "Bearer plain-token", "password=x", "token=x", "secret=x",
    "eyJabc.eyJdef.abcdef", "postgres://user:password@db/prod",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-content\n-----END OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----\ntruncated-private-body",
])
def test_all_credential_formats_are_removed_and_idempotent(secret):
    result = redact_string("before " + secret)
    assert secret not in result and "[REDACTED]" in result
    assert redact_string(result) == result


def test_nested_sensitive_containers_and_types_are_preserved():
    source = {"items": [{"password": "x", "Authorization": {"nested": "abc"}, "clientSecret": ["one", "two"]}], "safe": [1, False, None]}
    body, changed = redact_body(json.dumps(source))
    assert changed
    value = json.loads(body)
    assert value["items"][0] == {"password": "[REDACTED]", "Authorization": "[REDACTED]", "clientSecret": "[REDACTED]"}
    assert value["safe"] == source["safe"] and source["items"][0]["password"] == "x"
    assert redact_body(body) == (body, False)


def test_policy_combinations_and_real_change_flag():
    scanner = SecurityScanner()
    body = '{"content":"AKIAABCDEFGHIJKLMNOP"}'
    assert scanner.scan(body, "request", SecuritySettings(mode="audit", redact_secrets=True)).sanitized
    assert not scanner.scan(body, "request", SecuritySettings(mode="audit", redact_secrets=False)).sanitized
    assert scanner.scan(body, "request", SecuritySettings(mode="redact", redact_secrets=False)).sanitized
    assert not scanner.scan(body, "request", SecuritySettings(enabled=False)).sanitized
    assert not scanner.scan('{"content":"DROP TABLE demo"}', "request", SecuritySettings(mode="redact")).sanitized
    rule = SecurityCustomRuleEntity(id="deny", pattern="AKIA", category="keyword", action="block")
    blocked = scanner.scan(body, "request", SecuritySettings(), [rule])
    assert blocked.blocked and not blocked.sanitized


def test_disabled_custom_redaction_and_literal_metacharacters():
    rules = [SecurityCustomRuleEntity(id="off", enabled=0, category="keyword", pattern="keep", action="redact"),
             SecurityCustomRuleEntity(id="on", category="keyword", pattern="a.b", action="redact")]
    result = SecurityScanner().scan('{"content":"keep axb a.b"}', "request", SecuritySettings(redact_secrets=False), rules)
    assert json.loads(result.sanitized_body)["content"] == "keep axb [REDACTED]"
    assert result.sanitized


def test_limits_fail_explicitly_without_raw_scan_fallback():
    scanner = SecurityScanner()
    with pytest.raises(SecurityLimitError):
        scanner.scan(json.dumps({"content": "a" * 1_000_001}), "request", SecuritySettings())
    value = "safe"
    for _ in range(66):
        value = [value]
    with pytest.raises(SecurityLimitError):
        scanner.scan(json.dumps(value), "request", SecuritySettings())
