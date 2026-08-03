"""Security scanner with 6 sub-scanners: credential, path, unicode, network, tool, tracking."""
import re
import hashlib
import uuid
import logging
from datetime import datetime, timezone
from typing import List

from app.domain.entities import SecurityFindingEntity, SecurityScanResult
from app.types.enums import RiskLevel, SEVERITY_SCORES

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
    return datetime.now(timezone.utc).isoformat()


def _make_finding(rule_id, title, description, severity, category, evidence, json_path, phase) -> SecurityFindingEntity:
    return SecurityFindingEntity(
        id=str(uuid.uuid4()), phase=phase, category=category, rule_id=rule_id,
        severity=severity, title=title, description=description, location=json_path,
        evidence_masked=mask_evidence(evidence), evidence_hash=hash_evidence(evidence),
        action="warn", created_at=_now(),
    )


# ---- Sub-scanner rule definitions ----

CREDENTIAL_RULES = [
    ("credential_apikey_openai", "OpenAI API Key", "Detected OpenAI-style API key (sk-...).", r"sk-[a-zA-Z0-9]{20,}", "high"),
    ("credential_apikey_generic", "Generic API Key", "Detected generic API key pattern (key-...).", r"key-[a-zA-Z0-9]{20,}", "high"),
    ("credential_apikey_google", "Google API Key", "Detected Google API key (AIza...).", r"AIza[a-zA-Z0-9_-]{35}", "high"),
    ("credential_private_key", "Private Key", "Detected PEM-encoded private key.", r"-----BEGIN.*PRIVATE KEY-----", "critical"),
    ("credential_private_key_rsa", "RSA Private Key", "Detected PEM-encoded RSA private key.", r"-----BEGIN.*RSA.*-----", "critical"),
    ("credential_jwt", "JWT Token", "Detected a JSON Web Token.", r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", "high"),
    ("credential_aws_access", "AWS Access Key ID", "Detected AWS access key ID (AKIA...).", r"AKIA[0-9A-Z]{16}", "critical"),
    ("credential_github_pat", "GitHub PAT", "Detected GitHub personal access token (ghp_...).", r"ghp_[a-zA-Z0-9]{36}", "critical"),
    ("credential_slack_token", "Slack Token", "Detected Slack token (xox...).", r"xox[baprs]-[a-zA-Z0-9-]+", "high"),
    ("credential_password", "Password Assignment", "Detected password assignment in plaintext.", r"password\s*[=:]\s*\S+", "high"),
    ("credential_token", "Token Assignment", "Detected token assignment in plaintext.", r"token\s*[=:]\s*\S+", "high"),
    ("credential_secret", "Secret Assignment", "Detected secret assignment in plaintext.", r"secret\s*[=:]\s*\S+", "high"),
]

PATH_RULES = [
    ("path_traversal_basic", "Path Traversal", "Detected directory traversal sequence (../).", r"\.\./", "high"),
    ("path_traversal_encoded", "Encoded Path Traversal", "Detected URL-encoded path traversal.", r"%2e%2e%2f|%2e%2e/|\.\.%2f", "high"),
    ("path_absolute_unix", "Absolute Unix Path", "Detected absolute Unix path access attempt.", r"/etc/passwd|/etc/shadow|/root/", "critical"),
    ("path_absolute_win", "Absolute Windows Path", "Detected absolute Windows path access attempt.", r"[Cc]:\\[Ww]indows|[Cc]:\\[Uu]sers", "critical"),
    ("path_dev_null", "Dev Null Redirect", "Detected redirect to /dev/null.", r"/dev/null", "medium"),
]

NETWORK_RULES = [
    ("network_ssrf_localhost", "SSRF Localhost", "Detected localhost/internal IP reference — possible SSRF.", r"(localhost|127\.0\.0\.1|0\.0\.0\.0|::1)", "high"),
    ("network_ssrf_internal", "SSRF Internal IP", "Detected internal/private IP address reference.", r"(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)\d+\.\d+", "high"),
    ("network_ssrf_metadata", "SSRF Cloud Metadata", "Detected cloud metadata endpoint reference.", r"169\.254\.169\.254|metadata\.google\.internal", "critical"),
    ("network_url_http", "HTTP URL", "Detected plain HTTP URL reference.", r"http://[^\s\"'<>]+", "low"),
    ("network_url_leak", "URL with credentials", "Detected URL with embedded credentials.", r"https?://[^\s:/@]+:[^\s:/@]+@", "high"),
]

UNICODE_RULES = [
    ("unicode_homoglyph_cyrillic", "Cyrillic Homoglyph", "Detected Cyrillic characters that mimic Latin letters — possible homograph attack.", r"[\u0400-\u04FF]", "medium"),
    ("unicode_homoglyph_greek", "Greek Homoglyph", "Detected Greek characters that mimic Latin letters.", r"[\u0370-\u03FF]", "medium"),
    ("unicode_zero_width", "Zero-Width Character", "Detected zero-width/invisible Unicode characters.", r"[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]", "high"),
    ("unicode_right_to_left", "RTL Override", "Detected right-to-left override character — possible text obfuscation.", r"[\u202D\u202E]", "high"),
    ("unicode_fullwidth", "Fullwidth Character", "Detected fullwidth Unicode characters.", r"[\uFF00-\uFFEF]", "low"),
]

TOOL_RULES = [
    ("tool_cmd_exec", "Command Execution", "Detected system command execution function call.", r"(os\.system|subprocess\.call|subprocess\.Popen|eval\(|exec\()", "critical"),
    ("tool_file_write", "File Write", "Detected file write operation.", r"(open\([^)]*['\"]w|writeFile|fs\.write)", "high"),
    ("tool_file_read", "File Read", "Detected file read operation.", r"(open\([^)]*['\"]r|readFile|fs\.read|/etc/passwd)", "high"),
    ("tool_sql_injection", "SQL Injection Pattern", "Detected potential SQL injection pattern.", r"(DROP\s+TABLE|UNION\s+SELECT|;\s*DELETE\s+FROM)", "critical"),
    ("tool_xss", "XSS Pattern", "Detected potential XSS payload.", r"(<script|javascript:|onerror\s*=|onload\s*=)", "high"),
    ("tool_prompt_injection", "Prompt Injection", "Detected prompt injection attempt.", r"(ignore\s+(previous|above)\s+instructions|disregard\s+(all|previous)|you\s+are\s+now\s+a)", "high"),
]

TRACKING_RULES = [
    ("tracking_ga", "Google Analytics", "Detected Google Analytics tracking reference.", r"google-analytics\.com|googletagmanager\.com", "low"),
    ("tracking_fb_pixel", "Facebook Pixel", "Detected Facebook Pixel tracking reference.", r"connect\.facebook\.net|fbq\(", "low"),
    ("tracking_hotjar", "Hotjar", "Detected Hotjar tracking script.", r"hotjar\.com", "low"),
    ("tracking_mixpanel", "Mixpanel", "Detected Mixpanel analytics tracking.", r"mixpanel\.com", "low"),
    ("fingerprint_canvas", "Canvas Fingerprinting", "Detected canvas.toDataURL() — browser fingerprinting.", r"canvas\.toDataURL\(\)", "medium"),
    ("fingerprint_useragent", "User-Agent Collection", "Detected navigator.userAgent access.", r"navigator\.userAgent", "medium"),
    ("fingerprint_device", "Device Fingerprint", "Detected deviceFingerprint reference.", r"deviceFingerprint", "medium"),
]


def _run_rules(rules, text, json_path, phase, category) -> List[SecurityFindingEntity]:
    findings = []
    if not text:
        return findings
    for rule_id, title, desc, pattern, severity in rules:
        for m in re.finditer(pattern, text):
            findings.append(_make_finding(rule_id, title, desc, severity, category, m.group(), json_path, phase))
    return findings


def _walk_json(obj, path, phase, settings, findings):
    """Recursively walk JSON and run scanners on string values."""
    if isinstance(obj, str):
        _run_all_scanners(obj, path, phase, settings, findings)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_json(v, f"{path}.{k}", phase, settings, findings)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_json(v, f"{path}[{i}]", phase, settings, findings)


def _run_all_scanners(text, json_path, phase, settings, findings):
    findings.extend(_run_rules(CREDENTIAL_RULES, text, json_path, phase, "credentials"))
    findings.extend(_run_rules(PATH_RULES, text, json_path, phase, "path"))
    findings.extend(_run_rules(NETWORK_RULES, text, json_path, phase, "network"))
    if settings.scan_unicode:
        findings.extend(_run_rules(UNICODE_RULES, text, json_path, phase, "unicode"))
    if settings.scan_tools:
        findings.extend(_run_rules(TOOL_RULES, text, json_path, phase, "tools"))
    findings.extend(_run_rules(TRACKING_RULES, text, json_path, phase, "tracking"))


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

    def scan(self, body: str, phase: str, settings) -> SecurityScanResult:
        if not body:
            return SecurityScanResult(risk_level="Clean", summary="Empty body — no findings.")
        if not settings.enabled:
            return SecurityScanResult(risk_level="Clean", summary="Security scanner is disabled.")

        findings = []
        import json
        try:
            parsed = json.loads(body)
            _walk_json(parsed, "$", phase, settings, findings)
        except Exception:
            _run_all_scanners(body, "$raw", phase, settings, findings)

        _run_all_scanners(body, "$raw", phase, settings, findings)

        deduped = _deduplicate(findings)
        risk_score = _calculate_risk_score(deduped)
        risk_level = RiskLevel.from_score(risk_score)

        blocked = False
        blocked_reason = None
        sanitized = False

        mode = settings.mode or "audit"
        if mode == "block":
            if risk_level == "Critical" and settings.block_on_critical:
                blocked = True
                blocked_reason = f"Critical security finding detected: {risk_level}"
        elif mode == "redact":
            if settings.redact_secrets and risk_level in ("High", "Critical"):
                sanitized = True

        return SecurityScanResult(
            risk_level=risk_level, risk_score=risk_score,
            summary=_summarize(deduped), findings=deduped,
            blocked=blocked, blocked_reason=blocked_reason, sanitized=sanitized,
        )
