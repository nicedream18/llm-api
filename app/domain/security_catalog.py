"""Builtin detector definitions and default policy metadata."""
import re
from dataclasses import dataclass

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

ENTROPY_RULE_ID = "credential_high_entropy"
ENTROPY_THRESHOLD = 4.5
ENTROPY_MIN_LENGTH = 20
_ENTROPY_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{20,}(?![A-Za-z0-9+/=_-])")
_KNOWN_CREDENTIAL_PATTERNS = tuple(re.compile(rule[3]) for rule in CREDENTIAL_RULES)
_PEM_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

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


@dataclass(frozen=True)
class BuiltinRule:
    rule_id: str
    title: str
    description: str
    pattern: str | None
    severity: str
    category: str
    toggle_key: str | None = None
    action: str = "warn"

    @property
    def id(self) -> str:
        if self.rule_id == ENTROPY_RULE_ID:
            return "builtin-credential-high-entropy"
        return "builtin-" + self.rule_id


RULE_GROUPS = (
    ("credentials", CREDENTIAL_RULES, None),
    ("path", PATH_RULES, None),
    ("network", NETWORK_RULES, "security.scan_network"),
    ("unicode", UNICODE_RULES, "security.scan_unicode"),
    ("tools", TOOL_RULES, "security.scan_tools"),
    ("tracking", TRACKING_RULES, None),
)
BUILTIN_RULES = tuple(
    BuiltinRule(*definition, category, toggle)
    for category, rules, toggle in RULE_GROUPS for definition in rules
) + (BuiltinRule(
    ENTROPY_RULE_ID, "High-Entropy Credential Candidate",
    "Standalone token with Shannon entropy above 4.5 bits per character; review as a possible secret.",
    None, "medium", "credentials",
),)
RULE_BY_ID = {rule.rule_id: rule for rule in BUILTIN_RULES}
