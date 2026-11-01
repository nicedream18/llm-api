from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import routes
from app.types.auth import AuthContext


class RecordingService:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "get_api_key":
                return SimpleNamespace(id=args[0], quota_limit=100, quota_used=25)
            return {"operation": name}

        return call


def make_client(monkeypatch):
    channel = RecordingService()
    dashboard = RecordingService()
    agent = RecordingService()
    security = RecordingService()
    mcp = RecordingService()
    software = RecordingService()
    audit = RecordingService()
    mcp.list_tools = lambda _context=None: {"tools": [{"name": "test_tool"}]}
    mcp.call_tool = lambda name, arguments, context=None, request_id=None: {
        "name": name, "arguments": arguments, "request_id": request_id,
    }
    container = SimpleNamespace(
        channel_service=channel,
        dashboard_service=dashboard,
        agent_service=agent,
        security_service=security,
        mcp_service=mcp,
        software_service=software,
        software_repo=software,
        mcp_audit_repo=audit,
    )
    monkeypatch.setattr(routes, "get_container", lambda: container)
    app = FastAPI()
    for router in (
        routes.channel_router,
        routes.apikey_router,
        routes.dashboard_router,
        routes.agent_router,
        routes.security_router,
        routes.mcp_router,
        routes.software_router,
    ):
        app.include_router(router)

    @app.middleware("http")
    async def add_admin_context(request, call_next):
        request.state.auth_context = AuthContext("admin", "admin-1", "operator")
        request.state.request_id = "request-1"
        return await call_next(request)

    return TestClient(app), {
        "channel": channel, "dashboard": dashboard, "agent": agent,
        "security": security, "mcp": mcp, "software": software,
        "audit": audit,
    }


def test_management_routes_dispatch_admin_operations_and_preserve_static_paths(monkeypatch):
    client, services = make_client(monkeypatch)

    exported = client.get("/api/v1/channels/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    client.post("/api/v1/channels/import", json={"channels": [{"name": "one"}]})
    client.get("/api/v1/channels")
    client.get("/api/v1/channels/channel-1")
    client.post("/api/v1/channels", json={"name": "one"})
    client.put("/api/v1/channels", json={"id": "channel-1", "name": "one"})
    client.delete("/api/v1/channels/channel-1")
    client.post("/api/v1/channels/channel-1/test")
    client.post("/api/v1/channels/channel-1/clone")
    client.post("/api/v1/channels/test-draft", json={"name": "draft"})
    client.post("/api/v1/channels/channel-1/sync-models")
    client.get("/api/v1/channels/channel-1/api-keys")
    client.post("/api/v1/channels/channel-1/api-keys", json={"name": "key"})
    client.put("/api/v1/channels/channel-1/api-keys/key-1", json={"name": "key"})
    client.delete("/api/v1/channels/channel-1/api-keys/key-1")

    client.get("/api/v1/api-keys")
    client.get("/api/v1/api-keys/key-1")
    quota = client.get("/api/v1/api-keys/key-1/quota")
    assert quota.json()["data"] == {
        "api_key_id": "key-1", "quota_limit": 100, "quota_used": 25,
        "quota_remaining": 75,
    }
    client.post("/api/v1/api-keys", json={"name": "client"})
    client.put("/api/v1/api-keys", json={"id": "key-1", "name": "client"})
    client.delete("/api/v1/api-keys/key-1")

    client.get("/api/v1/dashboard")
    client.get("/api/v1/stats/models")
    client.get("/api/v1/stats/token-trend?days=5")
    client.get("/api/v1/stats/daily-tokens?days=7")
    client.get("/api/v1/stats/route-flow")
    client.post("/api/v1/stats/clear")
    client.get("/api/v1/logs?model=model-a&page=2&size=5")
    client.get("/api/v1/logs/filter-options")
    client.get("/api/v1/logs/log-1")
    client.get("/api/v1/logs/log-1/attempts")
    client.delete("/api/v1/logs/log-1")
    client.delete("/api/v1/logs")
    before = client.delete("/api/v1/logs/before?cutoff=2026-01-01T00%3A00%3A00Z")
    client.delete("/api/v1/logs/by-channel/channel-1")

    client.get("/api/v1/agents")
    client.get("/api/v1/agents/agent-1")
    client.post("/api/v1/agents", json={"agent_name": "helper"})
    client.put("/api/v1/agents/agent-1", json={"agent_name": "helper"})
    client.delete("/api/v1/agents/agent-1")
    client.post("/api/v1/agents/session?agent_id=agent-1&user_id=user-1")
    client.post("/api/v1/agents/agent-1/chat", json={"message": "hi"})

    client.get("/api/v1/security/rules/builtin")
    client.put("/api/v1/security/rules/builtin/rule-1", json={"enabled": 0, "severity": "low"})
    client.get("/api/v1/security/rules/custom")
    client.post("/api/v1/security/rules/custom", json={"name": "custom"})
    client.put("/api/v1/security/rules/custom/rule-1", json={"name": "custom"})
    client.delete("/api/v1/security/rules/custom/rule-1")
    client.get("/api/v1/security/findings?page=2&size=5")
    client.get("/api/v1/security/findings/by-log/log-1")

    info = client.get("/api/mcp/info")
    assert info.json()["tools"] == ["test_tool"]
    client.post("/api/mcp/tools/list")
    called = client.post("/api/mcp/tools/call", json={"name": "test_tool", "arguments": {"q": "x"}})
    assert called.json()["arguments"] == {"q": "x"}
    client.get("/api/v1/mcp/audit?limit=3&offset=2")
    client.get("/api/v1/mcp/tools")
    client.post("/api/v1/mcp/tools/test_tool/call", json={"arguments": {"q": "x"}})

    client.get("/api/v1/software/instances")
    client.post("/api/v1/software/instances", json={"name": "cli", "connector_type": "cli"})
    client.put("/api/v1/software/instances/i-1", json={"name": "cli", "connector_type": "cli"})
    client.delete("/api/v1/software/instances/i-1")
    client.get("/api/v1/software/tools?instance_id=i-1")
    client.post("/api/v1/software/tools", json={"instance_id": "i-1", "name": "echo"})
    client.put("/api/v1/software/tools/t-1/enabled?enabled=false")
    client.delete("/api/v1/software/tools/t-1")
    client.post("/api/v1/software/tools/t-1/invoke", json={"arguments": {"q": "x"}, "approved": True})
    client.get("/api/v1/software/calls?limit=3")
    spec = {"openapi": "3.0.0", "servers": [{"url": "https://api.example.test"}], "paths": {"/health": {"get": {"operationId": "health"}}}}
    client.post("/api/v1/software/openapi/preview", json={"spec": spec})
    client.post("/api/v1/software/openapi/import", json={"name": "Example", "spec": spec})

    assert before.json()["data"]["operation"] == "delete_before"
    assert services["dashboard"].calls[-2][0] == "delete_before"
    assert services["dashboard"].calls[-1][0] == "delete_by_channel"
    assert services["agent"].calls[-1][0] == "chat"
    assert services["security"].calls[1][1] == ("rule-1", 0, "low")
    assert services["software"].calls[-4][0] == "invoke"
    assert services["audit"].calls[0][0] == "list"
    assert {call[0] for call in services["channel"].calls} == {
        "export_channels", "import_channels", "list_channels", "get_channel",
        "create_channel", "update_channel", "delete_channel", "test_channel",
        "clone_channel", "test_draft_channel", "sync_models",
        "list_channel_api_keys", "create_channel_api_key", "update_channel_api_key",
        "delete_channel_api_key", "list_api_keys", "get_api_key", "create_api_key",
        "update_api_key", "delete_api_key",
    }
    assert {call[0] for call in services["dashboard"].calls} == {
        "dashboard", "model_stats", "token_trend", "route_flow", "clear_stats",
        "logs", "filter_options", "get_log", "attempts", "delete_log",
        "delete_all_logs", "delete_before", "delete_by_channel",
    }
    assert {call[0] for call in services["agent"].calls} == {
        "list_agents", "get_agent", "create_agent", "update_agent", "delete_agent",
        "create_session", "chat",
    }
    assert {call[0] for call in services["security"].calls} == {
        "list_builtin_rules", "update_builtin_rule", "list_custom_rules",
        "create_custom_rule", "update_custom_rule", "delete_custom_rule",
        "list_findings", "get_findings_by_log_id",
    }
    assert {call[0] for call in services["software"].calls} == {
        "list_instances", "create_instance", "update_instance", "delete_instance",
        "list_tools", "create_tool", "set_tool_enabled", "delete_tool", "invoke",
        "list_calls", "preview_openapi", "import_openapi",
    }
