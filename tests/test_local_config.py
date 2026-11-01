"""Client configuration operations use only temporary homes and synthetic secrets."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.local_bridge import bridge
from app.local_cli import main
from app.local_config import (
    TARGETS,
    ClientConfigurations,
    file_lock,
    gateway_url,
    read_bytes,
)


@pytest.mark.parametrize("target", list(TARGETS))
def test_preview_apply_preserves_unknown_fields_and_restore_exact_bytes(tmp_path, target):
    manager = ClientConfigurations(tmp_path)
    path = manager.path(target); path.parent.mkdir(parents=True)
    original = b'# preserve this comment\nmodel="custom"\n[unknown]\nvalue="private-secret"\n' if target == "codex" else b'{"theme":"dark","arbitrary":"private-secret","env":{"EXISTING_TOKEN":"synthetic-token"}}\n'
    path.write_bytes(original)
    preview = manager.preview(target)
    assert "private-secret" not in str(preview) and "synthetic-token" not in str(preview)
    assert "diff" in preview and preview["expected_sha256"]
    assert path.read_bytes() == original
    result = manager.apply(target, preview["expected_sha256"])
    assert "private-secret" in path.read_text()
    if target == "codex": assert "# preserve this comment" in path.read_text()
    elif target == "claude-code": assert json.loads(path.read_text())["env"]["EXISTING_TOKEN"] == "synthetic-token"
    else: assert json.loads(path.read_text())["mcpServers"]["waliapi"]["args"][1] == "bridge"
    manager.restore(target, result["backup_id"])
    assert path.read_bytes() == original


def test_new_file_restore_and_concurrent_edit_are_safe(tmp_path):
    manager = ClientConfigurations(tmp_path)
    path = manager.path("codex")
    plan = manager.preview("codex")
    assert not path.parent.exists()
    result = manager.apply("codex", plan["expected_sha256"])
    path.write_text("model='user-change'\n")
    with pytest.raises(ValueError, match="restore refused"): manager.restore("codex", result["backup_id"])
    with pytest.raises(ValueError, match="preview again"): manager.apply("codex", plan["expected_sha256"])
    fresh = manager.preview("codex")
    result = manager.apply("codex", fresh["expected_sha256"])
    manager.restore("codex", result["backup_id"])
    assert "user-change" in path.read_text()
    other = ClientConfigurations(tmp_path / "new")
    result = other.apply("gemini", other.preview("gemini")["expected_sha256"])
    other.restore("gemini", result["backup_id"])
    assert not other.path("gemini").exists()


def test_invalid_size_shape_backup_tampering_and_links(tmp_path):
    manager = ClientConfigurations(tmp_path)
    path = manager.path("gemini"); path.parent.mkdir()
    path.write_text("[]")
    with pytest.raises(TypeError): manager.preview("gemini")
    path.write_bytes(b"x" * 2_000_001)
    with pytest.raises(ValueError, match="2 MB"): manager.preview("gemini")
    path.write_text("{}")
    result = manager.apply("gemini", manager.preview("gemini")["expected_sha256"])
    backup = path.parent / ".waliapi-backups" / (result["backup_id"] + ".bin")
    backup.write_text("tampered")
    with pytest.raises(ValueError, match="integrity"): manager.restore("gemini", result["backup_id"])
    with pytest.raises(ValueError): manager.restore("gemini", "../../file")
    with pytest.raises(ValueError): manager.path("../outside")
    with pytest.raises(ValueError): read_bytes(path.parent)
    link = tmp_path / "linked"
    try: link.symlink_to(tmp_path / "outside", target_is_directory=True)
    except OSError: pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(ValueError, match="Symbolic"): ClientConfigurations(link)


def test_competing_writers_require_fresh_preview_and_lock(tmp_path):
    manager = ClientConfigurations(tmp_path)
    plan = manager.preview("codex")
    def apply(_):
        try: manager.apply("codex", plan["expected_sha256"]); return True
        except (OSError, ValueError): return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(apply, range(4))) == 1
    with file_lock(manager.path("codex").parent / ".waliapi-config.lock"), pytest.raises(FileExistsError):
        manager.apply("codex", manager.preview("codex")["expected_sha256"])


@pytest.mark.parametrize("url", ["http://user:pass@localhost:9900", "http://localhost:9900?token=secret", "file:///tmp/config", "http://example.com", "http://localhost:9900/v1"])
def test_gateway_addresses_reject_credentials_ssrf_schemes_and_implicit_remote(url):
    with pytest.raises(ValueError): gateway_url(url)
    assert gateway_url("https://gateway.example", True) == "https://gateway.example"


def test_detect_and_cli_are_explicit_redacted_and_failure_safe(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("app.local_config.shutil.which", lambda _: None)
    assert len(ClientConfigurations(tmp_path).detect()) == 4
    assert main(["config", "detect", "--home", str(tmp_path)]) == 0
    assert main(["config", "export", "--target", "codex", "--home", str(tmp_path)]) == 0
    assert not (tmp_path / ".codex").exists()
    capsys.readouterr()
    assert main(["config", "apply", "--target", "codex", "--home", str(tmp_path), "--expected-sha256", "wrong"]) == 1
    assert "Local operation failed" in capsys.readouterr().err
    with pytest.raises(SystemExit): main(["config", "apply", "--target", "codex"])
    with pytest.raises(SystemExit): main(["config", "restore", "--target", "codex"])
    with pytest.raises(SystemExit): main(["config", "preview"])


def test_bridge_json_sse_session_notifications_and_safe_failures(monkeypatch):
    monkeypatch.setenv("WALIAPI_MCP_TOKEN", "synthetic-mcp-token")
    calls = []
    def handler(request):
        value = json.loads(request.content); calls.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-mcp-token"
        if value["method"] == "initialize": return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}}, headers={"mcp-session-id": "session"})
        assert request.headers["mcp-session-id"] == "session"
        if "id" not in value: return httpx.Response(202)
        if value["id"] == 2: return httpx.Response(200, text='event: message\ndata: {"jsonrpc":"2.0",\ndata: "id":2,"result":{}}\n\n', headers={"content-type": "text/event-stream"})
        return httpx.Response(401, text="synthetic-mcp-token")
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize"}, {"method": "notifications/initialized"}, {"id": 2, "method": "tools/list"}, {"id": 3, "method": "tools/call"}]
    output = io.StringIO()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        bridge(io.StringIO("".join(json.dumps(value) + "\n" for value in messages)), output, "http://localhost:9900", client=client)
    results = [json.loads(value) for value in output.getvalue().splitlines()]
    assert [row["id"] for row in results] == [1, 2, 3]
    assert results[-1]["error"]["code"] == -32603
    assert "synthetic-mcp-token" not in output.getvalue() and len(calls) == 4


def test_bridge_rejects_missing_token_oversize_and_invalid_messages(monkeypatch):
    monkeypatch.delenv("WALIAPI_MCP_TOKEN", raising=False)
    with pytest.raises(ValueError, match="required"): bridge(io.StringIO(), io.StringIO(), "http://localhost")
    monkeypatch.setenv("WALIAPI_MCP_TOKEN", "synthetic-token")
    with pytest.raises(TypeError): bridge(io.StringIO("[]\n"), io.StringIO(), "http://localhost")
    with pytest.raises(ValueError, match="size"): bridge(io.StringIO("x" * 1_048_577), io.StringIO(), "http://localhost")
