"""Builtin detector definitions and default policy metadata."""
import math
import re
from dataclasses import dataclass

CREDENTIAL_RULES = [
    ("credential_apikey_openai", "OpenAI API Key", "Detected OpenAI-style API key (sk-...).", r"sk-(?:ant-|proj-|svcacct-)?[a-zA-Z0-9_-]{20,}", "high"),
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


# Additional article coverage, preserving all original rule identifiers.
CREDENTIAL_RULES.extend([
    ("credential_bearer", "Bearer Token", "Bearer authentication value.", r"(?i)\bBearer[ \t]+[A-Za-z0-9._~+/-]+=*", "high"),
    ("credential_database_url", "Database Connection", "Database connection string.", r"(?i)\b(?:mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis|mssql)://[^\s\"'<>]+", "high"),
    ("credential_cloud_key", "Cloud Credential", "Tencent or Alibaba cloud access key identifier.", r"\b(?:AKID[A-Za-z0-9]{16,64}|LTAI[A-Za-z0-9]{12,64})\b", "high"),
])
_KNOWN_CREDENTIAL_PATTERNS = tuple(re.compile(rule[3]) for rule in CREDENTIAL_RULES)
PATH_RULES.extend([
    ("file_sensitive_path", "Sensitive File", "Environment, SSH or cloud credential file.", r"(?i)(?:^|[/\\\s\"'])\.env(?:\.[\w-]+)?\b|(?:~[/\\])?\.ssh[/\\]|\.aws[/\\]credentials\b|(?:^|[/\\\s\"'])\.(?:npmrc|pypirc)\b", "high"),
    ("file_ssh_key", "SSH Key File", "SSH private key filename.", r"\bid_(?:rsa|ed25519|ecdsa|dsa)(?![\w.])", "critical"),
    ("infra_local_path", "Local User Path", "Local Unix user directory.", r"/(?:Users|home)/[^\s\"'<>]+", "medium"),
])
UNICODE_RULES.append(("unicode_variation_selector", "Variation Selector", "Unicode variation selector.", r"[\uFE00-\uFE0F\U000E0100-\U000E01EF]", "medium"))
NETWORK_RULES.extend([
    ("network_ip_probe", "Public IP Probe", "Public IP discovery service.", r"(?i)\b(?:ifconfig\.me|ipinfo\.io|api\.ipify\.org|icanhazip\.com|checkip\.amazonaws\.com)\b", "high"),
    ("network_suspicious_domain", "Suspicious Outbound Domain", "Temporary tunnel, webhook or paste service.", r"(?i)\b(?:webhook\.site|(?:[\w-]+\.)?ngrok(?:-free)?\.(?:io|app)|pastebin\.com|requestbin\.com)\b", "high"),
    ("network_external_url", "External URL", "External HTTPS URL.", r"https://[^\s\"'<>]+", "info"),
    ("network_tracking_pixel", "Tracking Pixel", "Tracking pixel, beacon or one-pixel image markup.", r"(?i)<img\b[^>\n]{0,1024}\b(?:width|height)\s*=\s*[\"']?1(?:[\"'\s>])|https?://[^\s\"'<>]{1,512}/(?:track|pixel|beacon)(?:[/?#.][^\s\"'<>]*)?", "high"),
])
TOOL_RULES.extend([
    ("tool_shell_network_or_exec", "Network or Shell Command", "Network utility or explicit shell execution.", r"\b(?:curl|wget|nc|netcat)\s+[^\n]{1,512}|\b(?:bash|sh)\s+-c\b", "medium"),
    ("tool_shell_exfiltration", "Sensitive Data Exfiltration", "Sensitive file reference and outbound command on the same line.", r"(?im)^(?=[^\n]{0,1024}(?:\.env\b|id_rsa\b|\.aws[/\\]credentials))(?=[^\n]{0,1024}\b(?:curl|wget|nc)\b)[^\n]{1,1024}", "critical"),
    ("tool_remote_script_exec", "Remote Script Execution", "Downloaded content piped or chained into a shell.", r"\b(?:curl|wget)\b[^\n]{0,512}(?:\||&&)\s*(?:bash|sh|zsh)\b", "critical"),
    ("tool_git_info", "Git Credential or Remote Information", "Git remote URL or CLI credential request.", r"\bgit\s+(?:remote(?:\s+-v)?|config\s+--get\s+remote\.[\w-]+\.url)\b|\bgh\s+auth\s+token\b", "low"),
])
# Extend the existing injection detector rather than creating a duplicate rule.
TOOL_RULES[:] = [
    (rid, title, desc, pattern + r"|忽略(?:之前|以上|所有).{0,8}(?:指令|规则)|绕过.{0,8}(?:审计|限制)|隐藏.{0,8}(?:操作|行为)|bypass\s+(?:audit|safety)", severity)
    if rid == "tool_prompt_injection" else (rid, title, desc, pattern, severity)
    for rid, title, desc, pattern, severity in TOOL_RULES
]
PERSONAL_RULES = [
    ("personal_email", "Email Address", "Email address.", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "low"),
    ("personal_phone", "Mainland China Mobile", "Mainland China mobile number.", r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)", "low"),
]
PROMPT_RULES = [
    ("prompt_fingerprint_context", "Fingerprint and Risk Context", "Combined timezone and proxy, fingerprint or risk-control context.", r"(?i)\A(?=[\s\S]{0,8192}(?:timezone|time zone|时区))(?=[\s\S]{0,8192}(?:proxy|代理|fingerprint|指纹|风控))[\s\S]{1,8192}", "medium"),
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
    ("personal", PERSONAL_RULES, None),
    ("prompt", PROMPT_RULES, None),
)
BUILTIN_RULES = tuple(
    BuiltinRule(*definition, category, toggle)
    for category, rules, toggle in RULE_GROUPS for definition in rules
) + (BuiltinRule(
    ENTROPY_RULE_ID, "High-Entropy Credential Candidate",
    "Standalone token with Shannon entropy above 4.5 bits per character; review as a possible secret.",
    None, "medium", "credentials",
),)
BUILTIN_RULES += (BuiltinRule("credential_named_secret", "Sensitive Credential Field", "Value in a sensitive JSON field.", None, "high", "credentials"),)
RULE_BY_ID = {rule.rule_id: rule for rule in BUILTIN_RULES}


def shannon_entropy(value: str) -> float:
    """Shannon entropy used by both detection and explicit redaction."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def entropy_matches(text: str):
    known = [match.span() for pattern in _KNOWN_CREDENTIAL_PATTERNS for match in pattern.finditer(text)]
    known.extend(match.span() for match in _PEM_PRIVATE_KEY_BLOCK.finditer(text))
    for match in _ENTROPY_CANDIDATE.finditer(text):
        if (ENTROPY_MIN_LENGTH <= len(match.group()) <= 256
                and shannon_entropy(match.group()) > ENTROPY_THRESHOLD
                and not any(match.start() < end and match.end() > start for start, end in known)):
            yield match
