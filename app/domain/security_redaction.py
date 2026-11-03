"""Recursive JSON credential redaction shared by scanner, proxy and audit logs."""
from __future__ import annotations

import json
import re

from app.domain.security_catalog import _PEM_PRIVATE_KEY_BLOCK, CREDENTIAL_RULES
from app.domain.security_matching import custom_matches
from app.domain.security_values import is_secret_field

REDACTED = "[REDACTED]"
MAX_TEXT_LENGTH = 1_000_000
MAX_DEPTH = 64
MAX_NODES = 100_000
# Preserve all original detection formats and include modern OpenAI key separators.
_SECRET_PATTERNS = tuple(re.compile(rule[3]) for rule in CREDENTIAL_RULES) + (
    re.compile(r"\bsk-(?:ant-|proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),
)


class SecurityLimitError(ValueError):
    """A security operation could not inspect the complete value."""


def validate_value(value, depth=0, budget=None):
    budget = [MAX_NODES] if budget is None else budget
    budget[0] -= 1
    if depth > MAX_DEPTH or budget[0] < 0:
        raise SecurityLimitError("Security JSON structure limit exceeded")
    if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
        raise SecurityLimitError("Security text limit exceeded")
    if isinstance(value, dict):
        for key, child in value.items():
            validate_value(key, depth + 1, budget)
            validate_value(child, depth + 1, budget)
    elif isinstance(value, list):
        for child in value:
            validate_value(child, depth + 1, budget)


def redact_string(value: str, custom_rules=(), tool_name=None) -> str:
    if len(value) > MAX_TEXT_LENGTH:
        raise SecurityLimitError("Security text limit exceeded")
    result = _PEM_PRIVATE_KEY_BLOCK.sub(REDACTED, value)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    # A private-key header without a terminator must not leave its body behind.
    result = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*", REDACTED, result)
    spans: list[tuple[int, int]] = []
    for rule in custom_rules or []:
        if getattr(rule, "rule_type", "blacklist") != "blacklist" or (getattr(rule, "action", None) or "").lower() not in {"sanitize", "redact"}:
            continue
        spans.extend((m.start, m.end) for m in custom_matches(rule, result, tool_name))
    # Merge overlapping matches, then rewrite once to preserve span offsets.
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        result = result[:start] + REDACTED + result[end:]
    return result


def redact_json(value, custom_rules=(), *, credentials=True, tool_name=None):
    """Return a copy, preserving non-sensitive JSON types."""
    if isinstance(value, dict):
        function = value.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            tool_name = function["name"]
        return {
            key: REDACTED if credentials and is_secret_field(key) and child not in (None, "", REDACTED)
            else redact_json(child, custom_rules, credentials=credentials, tool_name=tool_name)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_json(child, custom_rules, credentials=credentials, tool_name=tool_name) for child in value]
    if isinstance(value, str):
        if credentials:
            return redact_string(value, custom_rules, tool_name)
        # Custom actions must work even when the automatic credential mode is off.
        spans = [m for rule in custom_rules or []
                 if getattr(rule, "rule_type", "blacklist") == "blacklist"
                 and (getattr(rule, "action", None) or "").lower() in {"sanitize", "redact"}
                 for m in custom_matches(rule, value, tool_name)]
        result = value
        for match in sorted(spans, key=lambda m: m.start, reverse=True):
            result = result[:match.start] + REDACTED + result[match.end:]
        return result
    return value


def redact_body(body: str, custom_rules=(), *, credentials=True) -> tuple[str, bool]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        result = redact_string(body, custom_rules) if credentials else redact_json(body, custom_rules, credentials=False)
        return result, result != body
    validate_value(value)
    result = redact_json(value, custom_rules, credentials=credentials)
    if result == value:
        return body, False
    return json.dumps(result, ensure_ascii=False), True
