"""Recursive JSON credential redaction shared by scanner, proxy and audit logs."""
from __future__ import annotations

import json
import re

from app.domain.security_catalog import (
    _PEM_PRIVATE_KEY_BLOCK,
    CREDENTIAL_RULES,
    RULE_BY_ID,
    entropy_matches,
)
from app.domain.security_matching import (
    custom_matches,
    is_whitelisted,
    whitelist_category,
)
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


def redact_string(value: str, custom_rules=(), tool_name=None, builtin_rule_ids=()) -> str:
    if len(value) > MAX_TEXT_LENGTH:
        raise SecurityLimitError("Security text limit exceeded")
    result = _PEM_PRIVATE_KEY_BLOCK.sub(REDACTED, value)
    # Handle incomplete blocks before header-only detectors consume the header.
    result = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*", REDACTED, result)
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return _redact_explicit(result, custom_rules, tool_name, builtin_rule_ids)


def _redact_explicit(value, custom_rules, tool_name, builtin_rule_ids):
    spans: list[tuple[int, int]] = []
    for rule in custom_rules or []:
        if getattr(rule, "rule_type", "blacklist") == "blacklist" and (getattr(rule, "action", None) or "").lower() in {"sanitize", "redact"}:
            spans.extend((m.start, m.end) for m in custom_matches(rule, value, tool_name))
    for rule_id in builtin_rule_ids:
        builtin = RULE_BY_ID.get(rule_id)
        if builtin is None:
            continue
        if rule_id in {"credential_private_key", "credential_private_key_rsa"}:
            matches = re.finditer(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END \1-----|$)", value)
        elif builtin.pattern:
            matches = re.finditer(builtin.pattern, value)
        elif rule_id == "credential_high_entropy":
            matches = entropy_matches(value)
        else:
            continue
        for match in matches:
            scope = whitelist_category(rule_id, builtin.category)
            if not scope or not is_whitelisted(scope, value, match.start(), match.end(), custom_rules, tool_name):
                spans.append(match.span())
    return _replace_spans(value, spans)


def _replace_spans(value: str, spans: list[tuple[int, int]]) -> str:
    """Merge overlapping matches before rewriting to preserve original offsets."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        value = value[:start] + REDACTED + value[end:]
    return value


def redact_json(value, custom_rules=(), *, credentials=True, tool_name=None, path="$", builtin_rule_ids=()):
    """Return a copy, preserving non-sensitive JSON types."""
    if isinstance(value, dict):
        from app.domain.security_values import structured_tool_name
        tool_name = structured_tool_name(value, path, tool_name)
        return {
            key: REDACTED if (credentials or "credential_named_secret" in builtin_rule_ids) and is_secret_field(key) and child not in (None, "", REDACTED)
            else redact_json(child, custom_rules, credentials=credentials, tool_name=tool_name, path=f"{path}.{key}", builtin_rule_ids=builtin_rule_ids)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_json(child, custom_rules, credentials=credentials, tool_name=tool_name, path=f"{path}[{i}]", builtin_rule_ids=builtin_rule_ids) for i, child in enumerate(value)]
    if isinstance(value, str):
        if credentials:
            return redact_string(value, custom_rules, tool_name, builtin_rule_ids)
        # Custom actions must work even when the automatic credential mode is off.
        return _redact_explicit(value, custom_rules, tool_name, builtin_rule_ids)
    return value


def redact_body(body: str, custom_rules=(), *, credentials=True, builtin_rule_ids=()) -> tuple[str, bool]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        result = redact_string(body, custom_rules, builtin_rule_ids=builtin_rule_ids) if credentials else redact_json(body, custom_rules, credentials=False, builtin_rule_ids=builtin_rule_ids)
        return result, result != body
    validate_value(value)
    result = redact_json(value, custom_rules, credentials=credentials, builtin_rule_ids=builtin_rule_ids)
    if result == value:
        return body, False
    return json.dumps(result, ensure_ascii=False), True
