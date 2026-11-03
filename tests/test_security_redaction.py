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


def test_truncated_private_key_body_is_not_left_after_header_redaction():
    assert redact_string("before -----BEGIN RSA PRIVATE KEY-----\ntruncated-private-body") == "before [REDACTED]"


def test_custom_overlapping_redactions_and_direct_tool_context():
    rules = [SecurityCustomRuleEntity(id="first", category="keyword", pattern="abcdef", action="redact"),
             SecurityCustomRuleEntity(id="second", category="keyword", pattern="defghi", action="redact")]
    result, changed = redact_body('{"content":"abcdefghijk"}', rules, credentials=False)
    assert changed and json.loads(result)["content"] == "[REDACTED]jk"
    tool = SecurityCustomRuleEntity(id="tool", category="tool", pattern="dangerous", action="redact")
    source = {"tools": [{"name": "dangerous", "input": "unsafe content"}], "content": "safe"}
    result, changed = redact_body(json.dumps(source), [tool], credentials=False)
    assert changed and json.loads(result)["tools"][0]["input"] == "[REDACTED]"
    assert json.loads(result)["content"] == "safe"


def test_legacy_uppercase_custom_severity_is_effective_in_policy():
    rule = SecurityCustomRuleEntity(id="legacy", category="keyword", pattern="credential", severity="CRITICAL", action="WARN")
    result = SecurityScanner().scan('"credential"', "request", SecuritySettings(mode="block"), [rule])
    assert result.blocked and result.findings[0].severity == "critical"


@pytest.mark.parametrize("rule_id,text", [
    ("credential_aws_access", "AKIAABCDEFGHIJKLMNOP"),
    ("credential_private_key", "-----BEGIN PRIVATE KEY-----\nsecret-body\n-----END PRIVATE KEY-----"),
    ("credential_private_key_rsa", "-----BEGIN RSA PRIVATE KEY-----\ntruncated-private-body"),
    ("network_external_url", "https://private.example/x"),
    ("credential_high_entropy", "abcdefghijklmnopqrstuvwxyz0123456789"),
])
def test_builtin_explicit_redaction_works_with_independent_switch_off(rule_id, text):
    from app.domain.entities import SecurityBuiltinRuleEntity

    override = SecurityBuiltinRuleEntity(rule_id=rule_id, action="redact", severity="low")
    result = SecurityScanner().scan(json.dumps({"content": text}), "request", SecuritySettings(mode="audit", redact_secrets=False), builtin_rules=[override])
    assert result.sanitized and json.loads(result.sanitized_body)["content"] == "[REDACTED]"


def test_builtin_explicit_redaction_respects_local_whitelist_and_sensitive_containers():
    from app.domain.entities import SecurityBuiltinRuleEntity

    allow = SecurityCustomRuleEntity(id="allow", rule_type="whitelist", category="domain", pattern="safe.example", action="allow")
    override = SecurityBuiltinRuleEntity(rule_id="network_external_url", action="redact")
    result = SecurityScanner().scan('{"content":"https://safe.example https://private.example"}', "request", SecuritySettings(redact_secrets=False), [allow], [override])
    assert json.loads(result.sanitized_body)["content"] == "https://safe.example [REDACTED]"
    override = SecurityBuiltinRuleEntity(rule_id="credential_named_secret", action="redact")
    result = SecurityScanner().scan('{"password":["x"],"content":"safe"}', "request", SecuritySettings(redact_secrets=False), builtin_rules=[override])
    assert json.loads(result.sanitized_body) == {"password": "[REDACTED]", "content": "safe"}
