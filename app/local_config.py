"""Explicit, reversible client configuration edits confined to a selected home."""

import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import tomlkit

TARGETS = {"codex": ".codex/config.toml", "claude-code": ".claude/settings.json", "gemini": ".gemini/settings.json",
           "claude-desktop": "AppData/Roaming/Claude/claude_desktop_config.json" if os.name == "nt" else "Library/Application Support/Claude/claude_desktop_config.json" if sys.platform == "darwin" else ".config/Claude/claude_desktop_config.json"}
MAX_BYTES = 2_000_000
SECRET = re.compile(r"key|token|secret|password|authorization|cookie", re.IGNORECASE)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def safe_path(path):
    path = Path(path).absolute()
    if not path.exists() and not path.parent.exists():
        return path
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Symbolic links and junctions are not allowed")
    return path


def read_bytes(path):
    safe_path(path)
    if not path.exists(): return b""
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Configuration must be a regular file of at most 2 MB")
    with path.open("rb") as stream:
        value = stream.read(MAX_BYTES + 1)
    if len(value) > MAX_BYTES: raise ValueError("Configuration exceeds size limit")
    return value


def atomic_write(path, value):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix=".waliapi-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        safe_path(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@contextmanager
def file_lock(path):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        yield
    finally:
        path.unlink()


def redact(value, key="", safe_values=frozenset()):
    if SECRET.search(key) and key != "env_key": return "[REDACTED]"
    if isinstance(value, dict): return {name: redact(child, name, safe_values) for name, child in value.items()}
    if isinstance(value, list): return [redact(child, key, safe_values) for child in value]
    if isinstance(value, str) and value not in safe_values: return "[PRESERVED / REDACTED]"
    return value


def gateway_url(url, allow_remote=False):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Gateway URL must contain only HTTP scheme, host and port")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and (not allow_remote or parsed.scheme != "https"):
        raise ValueError("Remote gateways require explicit allow-remote and HTTPS")
    return url.rstrip("/")


class ClientConfigurations:
    def __init__(self, home=None):
        self.home = safe_path(home or Path.home())

    def path(self, target):
        if target not in TARGETS: raise ValueError("Unsupported client")
        return safe_path(self.home / TARGETS[target])

    def detect(self):
        return [{"target": target, "configuration": str(self.path(target)), "configured": self.path(target).is_file(),
                 "executable": str(safe_path(found)) if (found := shutil.which({"claude-code": "claude", "claude-desktop": "Claude"}.get(target, target))) else None} for target in TARGETS]

    def _prepare(self, target, url, allow_remote):
        path = self.path(target); original = read_bytes(path)
        base_url = gateway_url(url, allow_remote)
        source = original.decode("utf-8-sig")
        values = tomlkit.parse(source) if target == "codex" else json.loads(source) if source.strip() else {}
        if not isinstance(values, dict): raise TypeError("Configuration must be an object")
        safe_values = {base_url, base_url + "/v1", "waliapi", "WaLiAPI", "responses", "WALIAPI_API_KEY"}
        before = json.loads(json.dumps(redact(dict(values), safe_values=safe_values)))
        if target == "codex":
            values["model_provider"] = "waliapi"
            providers = values.setdefault("model_providers", {})
            providers["waliapi"] = {"name": "WaLiAPI", "base_url": base_url + "/v1", "env_key": "WALIAPI_API_KEY", "wire_api": "responses"}
            required_env = "WALIAPI_API_KEY"
        elif target == "claude-code":
            values.setdefault("env", {})["ANTHROPIC_BASE_URL"] = base_url
            required_env = "ANTHROPIC_AUTH_TOKEN"
        else:
            # Gemini and Desktop use MCP; the gateway does not expose Gemini's native model API.
            values.setdefault("mcpServers", {})["waliapi"] = {"command": sys.executable, "args": [str(Path(__file__).resolve().parents[1] / "scripts/waliapi_local.py"), "bridge", "--url", base_url, *(["--allow-remote"] if allow_remote else [])]}
            required_env = "WALIAPI_MCP_TOKEN"
        rendered = tomlkit.dumps(values) if target == "codex" else json.dumps(values, ensure_ascii=False, indent=2) + "\n"
        if len(rendered.encode()) > MAX_BYTES: raise ValueError("Resulting configuration exceeds size limit")
        preview = redact(dict(values), safe_values=safe_values)
        diff = "".join(difflib.unified_diff((json.dumps(before, indent=2) + "\n").splitlines(True), (json.dumps(preview, indent=2) + "\n").splitlines(True), fromfile="current (redacted)", tofile="proposed (redacted)"))
        return {"target": target, "path": str(path), "expected_sha256": sha(original), "required_environment": required_env, "preview": preview, "diff": diff}, original, rendered.encode()

    def preview(self, target, url="http://127.0.0.1:9900", allow_remote=False):
        return self._prepare(target, url, allow_remote)[0]

    def apply(self, target, expected_sha256, url="http://127.0.0.1:9900", allow_remote=False):
        path = self.path(target)
        with file_lock(path.parent / ".waliapi-config.lock"):
            plan, original, proposed = self._prepare(target, url, allow_remote)
            if plan["expected_sha256"] != expected_sha256: raise ValueError("Configuration changed; preview again")
            backup_id = uuid.uuid4().hex
            backup = safe_path(path.parent / ".waliapi-backups")
            existed = path.exists()
            atomic_write(backup / (backup_id + ".bin"), original)
            metadata = {"target": target, "existed": existed, "before": sha(original), "after": sha(proposed)}
            atomic_write(backup / (backup_id + ".json"), json.dumps(metadata).encode())
            if sha(read_bytes(path)) != expected_sha256: raise ValueError("Configuration changed during apply")
            atomic_write(path, proposed)
            return {"target": target, "backup_id": backup_id, "sha256": sha(proposed)}

    def restore(self, target, backup_id):
        if not re.fullmatch(r"[a-f0-9]{32}", backup_id): raise ValueError("Invalid backup ID")
        path = self.path(target)
        with file_lock(path.parent / ".waliapi-config.lock"):
            backup = path.parent / ".waliapi-backups"
            metadata = json.loads(read_bytes(backup / (backup_id + ".json")))
            original = read_bytes(backup / (backup_id + ".bin"))
            if metadata["target"] != target or metadata["before"] != sha(original): raise ValueError("Backup integrity mismatch")
            if metadata["after"] != sha(read_bytes(path)): raise ValueError("Configuration has changed; restore refused")
            if metadata["existed"]: atomic_write(path, original)
            else: path.unlink()
            return {"target": target, "restored": True}
