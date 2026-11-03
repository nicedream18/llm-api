"""Category-aware literal matching; whitelist scope never crosses a value."""
import ntpath
import posixpath
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RuleMatch:
    start: int
    end: int
    value: str


def normalize_host(value: str) -> str:
    candidate = value.strip().rstrip(".")
    parsed = urlsplit(candidate if "://" in candidate else "//" + candidate)
    host = parsed.hostname or ""
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def normalize_path(value: str) -> str:
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(value))
    return posixpath.normpath(value)


def literal_matches(category: str, pattern: str, text: str, tool_name: str | None = None) -> list[RuleMatch]:
    if not pattern:
        return []
    if category == "keyword":
        return [RuleMatch(m.start(), m.end(), m.group()) for m in re.finditer(re.escape(pattern), text, re.IGNORECASE)]
    if category == "tool":
        if tool_name == pattern:
            return [RuleMatch(0, len(text), text)]
        return []
    if category == "domain":
        wildcard = pattern.startswith("*.")
        expected = normalize_host(pattern[2:] if wildcard else pattern)
        matches = []
        for m in re.finditer(r"https?://[^\s\"'<>]+|(?<![\w@.-])(?:[\w-]+\.)+[A-Za-z]{2,63}(?![\w.-])", text, re.IGNORECASE):
            try:
                host = normalize_host(m.group().rstrip(",;)]}"))
            except (ValueError, UnicodeError):
                continue
            if expected and (host.endswith("." + expected) if wildcard else host == expected):
                matches.append(RuleMatch(m.start(), m.end(), m.group()))
        return matches
    if category == "path":
        expected = normalize_path(pattern)
        separator = "\\" if re.match(r"^[a-z]:", expected) or expected.startswith("\\\\") else "/"
        matches = []
        for m in re.finditer(r"(?:[A-Za-z]:[\\/]|~[/\\]|/)[^\s\"'<>|;]+", text):
            candidate = normalize_path(m.group().rstrip(",)]}"))
            if candidate == expected or candidate.startswith(expected.rstrip(separator) + separator):
                matches.append(RuleMatch(m.start(), m.end(), m.group()))
        return matches
    return []


def custom_matches(rule, text: str, tool_name: str | None = None) -> list[RuleMatch]:
    if not getattr(rule, "enabled", 1) or not rule.pattern:
        return []
    if getattr(rule, "match_type", "regex") == "literal":
        return literal_matches(rule.category, rule.pattern, text, tool_name)
    return [RuleMatch(m.start(), m.end(), m.group()) for m in re.finditer(rule.pattern, text)]


def is_whitelisted(category, text, start, end, rules, tool_name=None):
    return any(
        match.start <= start and match.end >= end
        for rule in rules or []
        if getattr(rule, "rule_type", "blacklist") == "whitelist" and rule.category == category
        and getattr(rule, "match_type", "regex") == "literal"
        for match in custom_matches(rule, text, tool_name)
    )


def whitelist_category(rule_id: str, category: str) -> str | None:
    if category in {"network", "tracking"}:
        return "domain"
    if category == "path":
        return "path"
    if category == "tools" and rule_id not in {"tool_shell_exfiltration", "tool_remote_script_exec", "tool_prompt_injection"}:
        return "tool"
    if category == "prompt":
        return "keyword"
    return None
