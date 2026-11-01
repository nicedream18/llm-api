from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.application.errors import ApplicationError
from app.application.services.software_service import SoftwareService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.software_repo import SoftwareRepository
from app.types.software import SoftwareInstanceInput, SoftwareToolInput


def test_software_schema_and_cli_connector_are_persisted(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
    repo = SoftwareRepository(engine)
    service = SoftwareService(repo)
    instance = service.create_instance(SoftwareInstanceInput(name="Echo", connector_type="cli", config={"command": ["python", "-c", "print('ok')"]}))
    tool = service.create_tool(SoftwareToolInput(instance_id=instance["id"], name="echo", approval_mode="none"))
    result = service.invoke(tool["id"], {})
    assert result["stdout"].strip() == "ok"
    assert repo.list_calls()[0]["status"] == "succeeded"
    assert {"software_instances", "software_tools", "software_call_logs"} <= set(inspect(engine).get_table_names())


def test_deleting_instance_removes_tools_calls_and_approvals_atomically(tmp_path):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
        execute_migration(db, Path("docs/migrations/016_software_approvals.sql"))
    repo = SoftwareRepository(engine)
    service = SoftwareService(repo)
    instance = service.create_instance(SoftwareInstanceInput(name="Echo", connector_type="cli", config={}))
    tool = service.create_tool(SoftwareToolInput(instance_id=instance["id"], name="echo", approval_mode="per_call"))
    approval = service.create_approval(tool["id"], {})
    repo.record_call({"tool_id": tool["id"], "status": "succeeded", "request_summary": "{}", "response_summary": "{}"})

    assert repo.delete_instance(instance["id"]) is True
    assert repo.get_instance(instance["id"]) is None
    assert repo.get_tool(tool["id"]) is None
    assert repo.get_approval(approval["id"]) is None
    assert repo.list_calls() == []
    assert repo.delete_instance(instance["id"]) is False


def test_software_requires_approval_and_rejects_shell_commands():
    class Repo:
        def get_tool(self, _id):
            return {"id": "tool", "instance_id": "instance", "enabled": 1, "approval_mode": "per_call", "config": "{}"}
        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "cli", "config": '{"command": ["echo"]}'}
        def record_call(self, values):
            self.call = values

    service = SoftwareService(Repo())
    with pytest.raises(ApplicationError, match="approval"):
        service.invoke("tool", {})


def test_local_software_scan_is_allowlisted_and_install_has_safe_dry_run(monkeypatch):
    from app.application.services.software_service import SoftwareService

    monkeypatch.setattr("app.application.services.software_service.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("app.application.services.software_service.subprocess.run", lambda command, **kwargs: type("Result", (), {"returncode": 0, "stdout": f"{command[0]} 1.0", "stderr": ""})())
    rows = SoftwareService.scan_local_tools(["python", "python", "unknown", "git"])
    assert [row["name"] for row in rows] == ["python", "git"]
    plan = SoftwareService.install_local_tool("example-package", "pip", dry_run=True)
    assert plan["status"] == "planned" and "example-package" in plan["command"]


def test_software_install_is_disabled_without_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("SOFTWARE_ALLOW_INSTALL", raising=False)
    with pytest.raises(ApplicationError, match="disabled"):
        SoftwareService.install_local_tool("example-package", "pip", dry_run=False)


def test_http_connector_blocks_private_targets(monkeypatch):
    class Repo:
        def get_tool(self, _id):
            return {"id": "tool", "instance_id": "instance", "enabled": 1, "approval_mode": "none", "config": '{}'}
        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "http", "config": '{"url": "http://127.0.0.1/private"}'}
        def record_call(self, values):
            self.call = values

    service = SoftwareService(Repo())
    with pytest.raises(ApplicationError):
        service.invoke("tool", {})


def test_software_credentials_require_env_references_and_are_resolved(monkeypatch):
    monkeypatch.setenv("SOFTWARE_TEST_TOKEN", "secret-token")

    class Repo:
        def get_tool(self, _id):
            return {
                "id": "tool", "instance_id": "instance", "enabled": 1,
                "approval_mode": "none", "risk_level": "low",
                "config": '{"headers":{"Authorization":{"env":"SOFTWARE_TEST_TOKEN"}}}',
                "input_schema": '{"type":"object"}',
            }

        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "http", "config": '{"url":"https://example.test"}'}

        def record_call(self, values):
            self.call = values

    class Response:
        status_code = 200
        content = b'{"ok":true}'
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    calls = []
    monkeypatch.setattr("app.application.services.software_service.ImportGuard.remote_url", lambda url: url)
    monkeypatch.setattr("app.application.services.software_service.httpx.request", lambda method, url, **kwargs: calls.append(kwargs) or Response())
    assert SoftwareService(Repo()).invoke("tool", {}) == {"ok": True}
    assert calls[0]["headers"]["Authorization"] == "secret-token"
    assert "secret-token" not in SoftwareService._safe_summary({"Authorization": "Bearer secret-token"})


def test_software_rejects_inline_credentials_and_missing_env(monkeypatch):
    with pytest.raises(ApplicationError, match="environment reference"):
        SoftwareService._validate_credential_config({"headers": {"Authorization": "Bearer inline"}})
    monkeypatch.delenv("MISSING_SOFTWARE_TOKEN", raising=False)
    with pytest.raises(ApplicationError, match="not configured"):
        SoftwareService._resolve_credential_config({"token": {"env": "MISSING_SOFTWARE_TOKEN"}})


def test_high_risk_tool_requires_admin_approval():
    class Repo:
        def get_tool(self, _id):
            return {"id": "tool", "instance_id": "instance", "enabled": 1, "approval_mode": "none", "risk_level": "high", "config": "{}", "input_schema": '{"type":"object"}'}

        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "cli", "config": '{"command":["echo"]}'}

        def record_call(self, values):
            self.call = values

    service = SoftwareService(Repo())
    with pytest.raises(ApplicationError, match="approval"):
        service.invoke("tool", {})
    with pytest.raises(ApplicationError, match="administrators"):
        service.invoke("tool", {}, principal=type("Principal", (), {"is_admin": False})(), approved=True)


def test_tool_input_schema_rejects_missing_unknown_and_wrong_type_arguments():
    class Repo:
        def get_tool(self, _id):
            return {
                "id": "tool",
                "instance_id": "instance",
                "enabled": 1,
                "approval_mode": "none",
                "config": "{}",
                "input_schema": '{"type":"object","required":["query"],"additionalProperties":false,"properties":{"query":{"type":"string"}}}',
            }

        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "cli", "config": '{"command":["echo"]}'}

        def record_call(self, values):
            self.call = values

    service = SoftwareService(Repo())
    with pytest.raises(ApplicationError, match="missing"):
        service.invoke("tool", {})
    with pytest.raises(ApplicationError, match="Unknown"):
        service.invoke("tool", {"query": "ok", "extra": True})
    with pytest.raises(ApplicationError, match="invalid type"):
        service.invoke("tool", {"query": 3})


def test_mcp_connector_initializes_and_calls_tool_with_session(monkeypatch):
    class Response:
        def __init__(self, payload, session_id=None):
            self.status_code = 200
            self.headers = {"content-type": "application/json"}
            if session_id:
                self.headers["mcp-session-id"] = session_id
            self.content = b"{}"
            self.text = ""
            self._payload = payload

        def json(self):
            return self._payload

    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        method = kwargs["json"]["method"]
        if method == "initialize":
            return Response({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}, "session-1")
        if method == "notifications/initialized":
            response = Response({}, None)
            response.status_code = 202
            return response
        return Response({"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "done"}]}})

    monkeypatch.setattr("app.application.services.software_service.ImportGuard.remote_url", lambda url: url)
    monkeypatch.setattr("app.application.services.software_service.httpx.post", fake_post)

    class Repo:
        def get_tool(self, _id):
            return {"id": "tool", "name": "search", "instance_id": "instance", "enabled": 1, "approval_mode": "none", "config": '{"url":"https://mcp.example.test","tool_name":"search"}', "input_schema": '{"type":"object"}'}

        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": "mcp", "config": "{}"}

        def record_call(self, values):
            self.call = values

    result = SoftwareService(Repo()).invoke("tool", {"query": "hello"})

    assert result == {"content": [{"type": "text", "text": "done"}]}
    assert calls[0][1]["json"]["method"] == "initialize"
    assert calls[0][1]["headers"]["MCP-Protocol-Version"] == "2025-06-18"
    assert calls[1][1]["json"]["method"] == "notifications/initialized"
    assert calls[1][1]["headers"]["Mcp-Session-Id"] == "session-1"
    assert calls[2][1]["json"]["method"] == "tools/call"


def test_software_approval_is_persistent_and_decision_is_single_use(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
        execute_migration(db, Path("docs/migrations/016_software_approvals.sql"))
    repo = SoftwareRepository(engine)
    service = SoftwareService(repo)
    instance = service.create_instance(SoftwareInstanceInput(name="Echo", connector_type="cli", config={"command": ["python", "-c", "print('approved')"]}))
    tool = service.create_tool(SoftwareToolInput(instance_id=instance["id"], name="echo", approval_mode="per_call"))
    approval = service.create_approval(tool["id"], {})
    assert approval["status"] == "pending"
    assert service.list_approvals()[0]["arguments"] == {}
    result = service.decide_approval(approval["id"], True)
    assert result["status"] == "executed" and result["result"]["stdout"].strip() == "approved"
    assert repo.get_approval(approval["id"])["status"] == "executed"
    with pytest.raises(ApplicationError, match="already decided"):
        service.decide_approval(approval["id"], False)


def test_software_approval_expiry_is_persisted_and_expired_requests_are_rejected():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    with engine.begin() as db:
        for migration in ("013_software_tools.sql", "016_software_approvals.sql", "019_software_approval_expiry.sql"):
            execute_migration(db, Path("docs/migrations") / migration)
    repo = SoftwareRepository(engine)
    service = SoftwareService(repo)
    instance = service.create_instance(SoftwareInstanceInput(name="Echo", connector_type="cli", config={"command": ["echo"]}))
    tool = service.create_tool(SoftwareToolInput(instance_id=instance["id"], name="echo", approval_mode="per_call"))
    approval = service.create_approval(tool["id"], {}, expires_in_seconds=60)
    assert approval["expires_at"]
    with engine.begin() as db:
        db.execute(
            __import__("sqlalchemy").text("UPDATE software_approval_expiry SET expires_at='2000-01-01T00:00:00+00:00' WHERE approval_id=:id"),
            {"id": approval["id"]},
        )
    with pytest.raises(ApplicationError, match="expired"):
        service.decide_approval(approval["id"], True)
    assert repo.get_approval(approval["id"])["status"] == "expired"


def test_software_approval_policy_can_override_tool_default():
    class Repo:
        def get_tool(self, _id):
            return {"id": "tool", "name": "read", "instance_id": "instance", "enabled": 1,
                    "approval_mode": "per_call", "risk_level": "low", "config": '{"operation":"read"}',
                    "input_schema": '{"type":"object"}'}

        def get_instance(self, _id):
            import sys
            return {"id": "instance", "enabled": 1, "connector_type": "cli",
                    "config": {"command": [sys.executable, "-c", "print('ok')"],
                               "approval_policy": {"operations": {"read": "none"}}}}

        def record_call(self, values):
            self.call = values

    assert SoftwareService(Repo()).invoke("tool", {})["stdout"].strip() == "ok"


def test_local_scan_normalizes_paths_and_deduplicates_aliases(tmp_path, monkeypatch):
    executable = tmp_path / "tool.exe"
    executable.write_text("stub", encoding="utf-8")
    monkeypatch.setattr("app.application.services.software_service.shutil.which", lambda name: str(executable))
    monkeypatch.setattr("app.application.services.software_service.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "tool 1", "stderr": ""})())
    rows = SoftwareService.scan_local_tools(["python", "python3"], timeout_seconds=1)
    assert len(rows) == 1 and rows[0]["path"] == str(executable.resolve())


def test_configured_wechat_and_clihub_connectors_use_safe_http_bridge(monkeypatch):
    class Response:
        status_code = 200
        content = b'{"ok":true}'
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    calls = []
    monkeypatch.setattr("app.application.services.software_service.ImportGuard.remote_url", lambda url: url)
    monkeypatch.setattr("app.application.services.software_service.httpx.request", lambda method, url, **kwargs: calls.append((method, url, kwargs)) or Response())

    class Repo:
        def __init__(self, connector):
            self.connector = connector

        def get_tool(self, _id):
            return {"id": "tool", "name": "send", "instance_id": "instance", "enabled": 1, "approval_mode": "none", "config": '{"url":"https://bridge.example.test/call"}', "input_schema": '{"type":"object"}'}

        def get_instance(self, _id):
            return {"id": "instance", "enabled": 1, "connector_type": self.connector, "config": "{}"}

        def record_call(self, values):
            self.call = values

    assert SoftwareService(Repo("wechat")).invoke("tool", {"message": "hi"}) == {"ok": True}
    assert SoftwareService(Repo("clihub")).invoke("tool", {"message": "hi"}) == {"ok": True}
    assert [call[1] for call in calls] == ["https://bridge.example.test/call", "https://bridge.example.test/call"]
