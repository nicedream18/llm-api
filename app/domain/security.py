"""Security scanner with 6 sub-scanners: credential, path, unicode, network, tool, tracking."""
import hashlib
import logging
import math
import re
import uuid
from datetime import UTC, datetime

from app.domain.entities import SecurityFindingEntity, SecurityScanResult
from app.domain.security_catalog import (
    _ENTROPY_CANDIDATE,
    _KNOWN_CREDENTIAL_PATTERNS,
    _PEM_PRIVATE_KEY_BLOCK,
    BUILTIN_RULES,
    ENTROPY_MIN_LENGTH,
    ENTROPY_RULE_ID,
    ENTROPY_THRESHOLD,
)
from app.domain.security_matching import (
    custom_matches,
    is_whitelisted,
    whitelist_category,
)
from app.types.enums import SEVERITY_SCORES, RiskLevel

logger = logging.getLogger(__name__)


def mask_evidence(evidence: str) -> str:
    if not evidence:
        return ""
    if "-----BEGIN" in evidence and "PRIVATE KEY" in evidence:
        return "-----BEGIN PRIVATE KEY----- [REDACTED]"
    prefixes = ["sk-", "key-", "AIza", "AKIA", "ghp_", "xox"]
    for p in prefixes:
        if evidence.startswith(p) and len(evidence) > 8:
            return evidence[:4] + "***" + evidence[-4:]
    if evidence.startswith("eyJ") and len(evidence) > 10:
        return evidence[:10] + "***"
    if len(evidence) > 20:
        return evidence[:20] + "***"
    return evidence


def hash_evidence(evidence: str) -> str:
    if not evidence:
        return ""
    return hashlib.sha256(evidence.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _make_finding(rule_id, title, description, severity, category, evidence, json_path, phase, action="warn") -> SecurityFindingEntity:
    return SecurityFindingEntity(
        id=str(uuid.uuid4()), phase=phase, category=category, rule_id=rule_id,
        severity=severity, title=title, description=description, location=json_path,
        evidence_masked=mask_evidence(evidence), evidence_hash=hash_evidence(evidence),
        action=(action or "warn").lower(), created_at=_now(),
    )


# ---- Sub-scanner rule definitions ----



def _run_rules(rules, text, json_path, phase, category, builtin_rules=None, custom_rules=None, tool_name=None) -> list[SecurityFindingEntity]:
    findings: list[SecurityFindingEntity] = []
    if not text:
        return findings
    text = text[:1_000_000]
    overrides = {getattr(rule, "rule_id", None): rule for rule in builtin_rules or []}
    for rule_id, title, desc, pattern, severity in rules:
        override = overrides.get(rule_id)
        if override is not None and not getattr(override, "enabled", 1):
            continue
        effective_severity = str(getattr(override, "severity", None) or severity).lower()
        action = getattr(override, "action", None) or "warn"
        try:
            matches = re.finditer(pattern, text)
            for m in matches:
                scope = whitelist_category(rule_id, category)
                if scope and is_whitelisted(scope, text, m.start(), m.end(), custom_rules, tool_name):
                    continue
                findings.append(_make_finding(rule_id, getattr(override, "name", None) or title, getattr(override, "description", None) or desc, effective_severity, category, m.group(), json_path, phase, action))
        except (re.error, RecursionError):
            logger.warning("Skipping invalid or unsafe security pattern", extra={"rule_id": rule_id})
    return findings


def _run_custom_rules(rules, text, json_path, phase, findings, tool_name=None):
    for rule in rules or []:
        if getattr(rule, "rule_type", "blacklist") == "whitelist":
            continue
        try:
            for match in custom_matches(rule, text, tool_name):
                findings.append(_make_finding(
                    rule.id or "custom", rule.name or "Custom security rule",
                    rule.description or "Custom security rule matched", rule.severity or "medium",
                    rule.category or "custom", match.value, json_path, phase,
                    getattr(rule, "action", None) or "warn"))
        except (re.error, RecursionError):
            logger.warning("Skipping invalid custom security pattern", extra={"rule_id": rule.id})


def _shannon_entropy(value: str) -> float:
    """Return Shannon entropy in bits per character for a candidate token."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _run_entropy_rule(text, json_path, phase, findings, builtin_rules=None):
    overrides = {getattr(rule, "rule_id", None): rule for rule in builtin_rules or []}
    override = overrides.get(ENTROPY_RULE_ID)
    if override is not None and not getattr(override, "enabled", 1):
        return

    severity = str(getattr(override, "severity", None) or "medium").lower()
    action = getattr(override, "action", None) or "warn"
    scan_text = text[:1_000_000]
    known_matches = [
        match.span()
        for pattern in _KNOWN_CREDENTIAL_PATTERNS
        for match in pattern.finditer(scan_text)
    ]
    known_matches.extend(match.span() for match in _PEM_PRIVATE_KEY_BLOCK.finditer(scan_text))
    for match in _ENTROPY_CANDIDATE.finditer(scan_text):
        candidate = match.group()
        if len(candidate) < ENTROPY_MIN_LENGTH or len(candidate) > 256:
            continue
        if any(match.start() < end and match.end() > start for start, end in known_matches):
            continue
        if _shannon_entropy(candidate) <= ENTROPY_THRESHOLD:
            continue
        findings.append(_make_finding(
            ENTROPY_RULE_ID,
            getattr(override, "name", None) or "High-Entropy Credential Candidate",
            getattr(override, "description", None) or f"Detected a {len(candidate)}-character token with Shannon entropy above {ENTROPY_THRESHOLD} bits per character; review it as a possible secret.",
            severity,
            "credentials",
            candidate,
            json_path,
            phase,
            action,
        ))


def _walk_json(obj, path, phase, settings, findings, custom_rules=None, builtin_rules=None, tool_name=None):
    """Recursively walk JSON and run scanners on string values."""
    if isinstance(obj, str):
        _run_all_scanners(obj, path, phase, settings, findings, custom_rules, builtin_rules, tool_name)
    elif isinstance(obj, dict):
        function = obj.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            tool_name = function["name"]
        elif isinstance(obj.get("name"), str) and any(part in path for part in (".tools[", ".tool_calls[", ".function")):
            tool_name = obj["name"]
        for k, v in obj.items():
            from app.domain.security_values import is_secret_field
            if is_secret_field(k) and v not in (None, "", "[REDACTED]"):
                override = next((r for r in builtin_rules or [] if r.rule_id == "credential_named_secret"), None)
                if getattr(override, "enabled", 1):
                    findings.append(_make_finding("credential_named_secret", getattr(override, "name", None) or "Sensitive Credential Field", getattr(override, "description", None) or "Value in a sensitive JSON field.", getattr(override, "severity", None) or "high", "credentials", str(v), f"{path}.{k}", phase, getattr(override, "action", None) or "warn"))
            _walk_json(v, f"{path}.{k}", phase, settings, findings, custom_rules, builtin_rules, tool_name)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_json(v, f"{path}[{i}]", phase, settings, findings, custom_rules, builtin_rules, tool_name)


def _run_all_scanners(text, json_path, phase, settings, findings, custom_rules=None, builtin_rules=None, tool_name=None):
    for rule in BUILTIN_RULES:
        override = next((r for r in builtin_rules or [] if r.rule_id == rule.rule_id), None)
        toggle = getattr(override, "toggle_key", None) or rule.toggle_key
        if toggle and not getattr(settings, toggle.removeprefix("security."), True):
            continue
        if rule.rule_id == ENTROPY_RULE_ID:
            _run_entropy_rule(text, json_path, phase, findings, builtin_rules)
        elif rule.pattern is not None:
            findings.extend(_run_rules([(rule.rule_id, rule.title, rule.description, rule.pattern, rule.severity)], text, json_path, phase, rule.category, builtin_rules, custom_rules, tool_name))
    _run_custom_rules(custom_rules, text, json_path, phase, findings, tool_name)


def _deduplicate(findings):
    seen = {}
    for f in findings:
        key = (f.rule_id, f.evidence_hash)
        if key not in seen:
            seen[key] = f
    return list(seen.values())


def _calculate_risk_score(findings):
    score = 0
    for f in findings:
        score += SEVERITY_SCORES.get(f.severity, 0)
    return min(score, 100)


def _summarize(findings):
    if not findings:
        return "No security findings."
    from collections import Counter
    counts = Counter(f.category for f in findings)
    parts = []
    for cat, cnt in counts.items():
        parts.append(f"{cnt} {cat}{'(s)' if cnt != 1 else ''}")
    return "Found " + ", ".join(parts) + "."


class SecurityScanner:
    """Main security scanner orchestrating all sub-scanners."""

    def scan(self, body: str, phase: str, settings, custom_rules=None, builtin_rules=None) -> SecurityScanResult:
        if not body:
            return SecurityScanResult(risk_level="Clean", summary="Empty body — no findings.")
        if not settings.enabled:
            return SecurityScanResult(risk_level="Clean", summary="Security scanner is disabled.")

        findings: list[SecurityFindingEntity] = []
        import json
        try:
            parsed = json.loads(body)
            _walk_json(parsed, "$", phase, settings, findings, custom_rules, builtin_rules)
        except Exception:  # noqa: BLE001 - raw scanner fallback handles malformed JSON
            _run_all_scanners(body, "$raw", phase, settings, findings, custom_rules, builtin_rules)

        if not findings:
            _run_all_scanners(body, "$raw", phase, settings, findings, custom_rules, builtin_rules)

        deduped = _deduplicate(findings)
        risk_score = _calculate_risk_score(deduped)
        risk_level = RiskLevel.from_score(risk_score)

        blocked = False
        blocked_reason = None
        sanitized = False
        sanitized_body = None

        mode = settings.mode or "audit"
        explicit_block = any((finding.action or "").lower() == "block" for finding in deduped)
        explicit_sanitize = any((finding.action or "").lower() in {"sanitize", "redact"} for finding in deduped)
        if explicit_block or (mode == "block" and risk_level == "Critical" and settings.block_on_critical):
            blocked = True
            blocked_reason = f"Critical security finding detected: {risk_level}"
        elif explicit_sanitize or (mode == "redact" and settings.redact_secrets and risk_level in ("High", "Critical")):
            sanitized = True
            sanitized_body = re.sub(r"(?i)(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36}|AIza[a-zA-Z0-9_-]{35}|eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", "[REDACTED]", body)
            for rule in custom_rules or []:
                if (getattr(rule, "action", None) or "").lower() in {"sanitize", "redact"}:
                    try:
                        sanitized_body = re.sub(rule.pattern, "[REDACTED]", sanitized_body)
                    except (re.error, TypeError):
                        logger.warning("Skipping invalid sanitization pattern", extra={"rule_id": getattr(rule, "id", None)})

        return SecurityScanResult(
            risk_level=risk_level, risk_score=risk_score,
            summary=_summarize(deduped), findings=deduped,
            blocked=blocked, blocked_reason=blocked_reason, sanitized=sanitized, sanitized_body=sanitized_body,
        )
