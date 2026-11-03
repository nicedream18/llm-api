import json

import pytest

from app.application.services.misc_services import SecurityService
from app.config import SecuritySettings
from app.domain.entities import SecurityCustomRuleEntity
from app.domain.security import SecurityScanner
from app.domain.security_matching import literal_matches
from app.types.models import SecurityCustomRuleDTO


@pytest.mark.parametrize("category,pattern,value,expected", [
    ("domain", "api.example.com", "https://API.example.com/x", True),
    ("domain", "example.com", "https://example.com.evil.test", False),
    ("domain", "example.com", "https://example.com@evil.test", False),
    ("domain", "*.example.com", "https://a.example.com", True),
    ("domain", "*.example.com", "https://example.com", False),
    ("path", "/Users/me/safe", "/Users/me/safe/file", True),
    ("path", "/Users/me/safe", "/Users/me/safe-other/file", False),
    ("path", "/Users/me/safe", "/Users/me/safe/../private", False),
    ("path", "/Users/me/safe", "/users/me/safe", False),
    ("path", r"C:\Users\Me\safe", r"c:\users\me\SAFE\file", True),
    ("keyword", "a.b", "A.B", True),
    ("keyword", "a.b", "axb", False),
])
def test_literal_boundaries(category, pattern, value, expected):
    assert bool(literal_matches(category, pattern, value)) is expected


def test_scoped_whitelist_keeps_other_values_secrets_and_blacklist():
    rules = [
        SecurityCustomRuleEntity(id="allow", rule_type="whitelist", match_type="literal", category="domain", pattern="webhook.site", action="allow"),
        SecurityCustomRuleEntity(id="deny", category="keyword", pattern="private", action="block"),
    ]
    result = SecurityScanner().scan(json.dumps({"a": "https://webhook.site/private", "b": "https://evil.example", "c": "sk-123456789012345678901234"}), "request", SecuritySettings(), rules)
    assert not any(f.rule_id == "network_suspicious_domain" for f in result.findings)
    assert any(f.rule_id == "network_external_url" for f in result.findings)
    assert any(f.rule_id == "credential_apikey_openai" for f in result.findings)
    assert result.blocked


def test_tool_matching_requires_structured_name_and_is_case_sensitive():
    rule = SecurityCustomRuleEntity(id="tool", category="tool", pattern="read_file", action="block")
    scanner = SecurityScanner()
    assert not scanner.scan('{"content":"read_file"}', "request", SecuritySettings(), [rule]).blocked
    assert scanner.scan('{"tool_calls":[{"function":{"name":"read_file","arguments":"{}"}}]}', "request", SecuritySettings(), [rule]).blocked
    rule.pattern = "Read_File"
    assert not scanner.scan('{"tool_calls":[{"function":{"name":"read_file"}}]}', "request", SecuritySettings(), [rule]).blocked


def test_custom_validation_and_partial_update(monkeypatch):
    from test_security_repository import _repository

    repo, _ = _repository(monkeypatch)
    service = SecurityService(repo)
    created = service.create_custom_rule(SecurityCustomRuleDTO(name="company", category="keyword", pattern="private", severity="HIGH", action="WARN"))
    assert created.severity == "high" and created.action == "warn"
    assert service.update_custom_rule(created.id, SecurityCustomRuleDTO(enabled=0))
    current = service.list_custom_rules()[0]
    assert current.pattern == "private" and current.name == "company" and current.enabled == 0
    assert not service.update_custom_rule("missing", SecurityCustomRuleDTO(enabled=0))
    for values in [
        {"pattern": ""}, {"pattern": "x", "category": "unknown"},
        {"pattern": "x", "category": "keyword", "rule_type": "whitelist", "action": "block"},
        {"pattern": "[", "match_type": "regex"},
        {"pattern": "(a+)+", "match_type": "regex"},
        {"pattern": "example.com/x", "category": "domain"},
    ]:
        with pytest.raises(ValueError):
            service.create_custom_rule(SecurityCustomRuleDTO(**values))
