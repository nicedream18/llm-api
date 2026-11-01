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
    assert calls[1][1]["json"]["method"] == "tools/call"
    assert calls[1][1]["headers"]["Mcp-Session-Id"] == "session-1"
