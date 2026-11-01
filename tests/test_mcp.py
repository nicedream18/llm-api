import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers.mcp_routes import PROTOCOL_VERSION, router
from app.api.controllers.routes import mcp_router
from app.api.middleware.auth import ApiKeyAuthMiddleware
from app.application.services.misc_services import McpService
from app.config import config

HEADERS = {
    "Authorization": "Bearer mcp-test-token",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL_VERSION,
}
INITIALIZE = {
    "protocolVersion": PROTOCOL_VERSION,
    "clientInfo": {"name": "test-client", "version": "1"},
    "capabilities": {},
}


@pytest.fixture
def setup_mcp(monkeypatch):
    kb = Mock()
    kb.list_kbs.return_value = [
        SimpleNamespace(id="kb-1", name="Manual", description="Docs", index_status="ready")
    ]
    kb.search_kb.return_value = [SimpleNamespace(score=0.9, content="Found text")]
    kb.ask.return_value = SimpleNamespace(answer="Answer", sources=[{"doc_id": "doc-1"}])
    kb.get_doc.return_value = SimpleNamespace(id="doc-1", name="Manual.md", status="ready")
    kb.list_docs.return_value = [SimpleNamespace(id="doc-1", name="Manual.md", status="ready")]
    kb.reindex_doc.return_value = {"success": True, "taskId": "task-1"}
    service = McpService(kb)
    container = SimpleNamespace(mcp_service=service, channel_repo=Mock())
    for module in ("app.api.controllers.mcp_routes", "app.api.controllers.routes", "app.api.middleware.auth"):
        monkeypatch.setattr(f"{module}.get_container", lambda: container)
    test_config = replace(config, auth=replace(config.auth, mcp_token="mcp-test-token", mcp_api_key_access=False))
    for module in ("app.api.middleware.auth", "app.application.services.auth_service", "app.api.controllers.mcp_routes"):
        monkeypatch.setattr(f"{module}.config", test_config)
    app = FastAPI()
    app.include_router(router)
    app.include_router(mcp_router)
    app.add_middleware(ApiKeyAuthMiddleware)
    return TestClient(app), kb, service


def rpc(client, method, params=None, rpc_id=1):
    message = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        message["params"] = params
    return client.post("/mcp", json=message, headers=HEADERS)


def test_initialize_and_notification_then_tool_workflow(setup_mcp):
    client, kb, _ = setup_mcp
    initialize_response = rpc(client, "initialize", INITIALIZE, rpc_id="init")
    initialized = initialize_response.json()
    session_id = initialize_response.headers["mcp-session-id"]
    assert initialized["id"] == "init"
    assert initialized["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert initialized["result"]["capabilities"] == {"tools": {"listChanged": False}}
    session_headers = {**HEADERS, "Mcp-Session-Id": session_id}
    response = client.post("/mcp", headers=session_headers, json={
        "jsonrpc": "2.0", "method": "notifications/initialized",
    })
    assert response.status_code == 202 and not response.content
    tools = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()["result"]["tools"]
    assert len(tools) == 16
    tools_by_name = {tool["name"]: tool for tool in tools}
    assert tools_by_name["search_knowledge_base"]["inputSchema"]["properties"]["top_k"]["maximum"] == 100
    listed = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_knowledge_bases"}}).json()["result"]
    assert json.loads(listed["content"][0]["text"])[0]["id"] == "kb-1"
    searched = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_knowledge_base", "arguments": {
        "kb_id": "kb-1", "query": "find", "top_k": 3,
    }}}).json()["result"]
    assert "Found text" in searched["content"][0]["text"]
    args = kb.search_kb.call_args.args
    assert args[0] == "kb-1" and args[1].top_k == 3
    asked = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ask_knowledge_base", "arguments": {
        "kb_id": "kb-1", "question": "why?",
    }}}).json()["result"]
    assert asked["content"][0]["text"] == "Answer"
    assert json.loads(asked["content"][1]["text"])["sources"] == [{"doc_id": "doc-1"}]
    document = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "get_knowledge_document", "arguments": {"kb_id": "kb-1", "doc_id": "doc-1"}}}).json()["result"]
    assert document["document"]["id"] == "doc-1"
    documents = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "list_knowledge_documents", "arguments": {"kb_id": "kb-1"}}}).json()["result"]
    assert documents["documents"][0]["name"] == "Manual.md"
    reindexed = client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "reindex_knowledge_document", "arguments": {"kb_id": "kb-1", "doc_id": "doc-1"}}}).json()["result"]
    assert reindexed["result"]["success"] is True


@pytest.mark.parametrize("arguments", [None, [], "text", 1, {}, {"kb_id": "k", "query": "q", "top_k": True},
    {"kb_id": "k", "query": "q", "top_k": 0}, {"kb_id": "k", "query": "q", "top_k": 101},
    {"kb_id": "k", "query": "q", "search_mode": "wrong"}, {"kb_id": "k", "query": "q", "extra": True}])
def test_invalid_tool_arguments_do_not_reach_kb(setup_mcp, arguments):
    client, kb, _ = setup_mcp
    result = rpc(client, "tools/call", {"name": "search_knowledge_base", "arguments": arguments}).json()
    assert result["error"]["code"] == -32602
    kb.search_kb.assert_not_called()


@pytest.mark.parametrize("message,code", [
    ([], -32600), ({"jsonrpc": "1.0", "id": 1, "method": "ping"}, -32600),
    ({"jsonrpc": "2.0", "id": True, "method": "ping"}, -32600),
    ({"jsonrpc": "2.0", "id": None, "method": "ping"}, -32600),
    ({"jsonrpc": "2.0", "id": 1, "method": 3}, -32600),
    ({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}, -32602),
])
def test_invalid_envelopes(setup_mcp, message, code):
    response = setup_mcp[0].post("/mcp", headers=HEADERS, json=message)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_rpc_errors_and_ping(setup_mcp):
    client, _, _ = setup_mcp
    assert rpc(client, "no-such-method").json()["error"]["code"] == -32601
    assert rpc(client, "tools/call", {"name": "no-such-tool"}).json()["error"]["code"] == -32602
    assert rpc(client, "initialize", {}).json()["error"]["code"] == -32602
    assert rpc(client, "tools/list", {"cursor": "unknown"}).json()["error"]["code"] == -32602
    assert rpc(client, "ping", rpc_id=0).json() == {"jsonrpc": "2.0", "id": 0, "result": {}}


def test_tool_errors_do_not_expose_secrets(setup_mcp, caplog):
    client, kb, _ = setup_mcp
    kb.list_kbs.side_effect = RuntimeError("mysql://private-password@internal-host")
    response = rpc(client, "tools/call", {"name": "list_knowledge_bases"})
    assert response.json()["result"]["isError"] is True
    assert "private-password" not in response.text
    assert "private-password" not in caplog.text


def test_notifications_do_not_execute_tools(setup_mcp):
    client, kb, _ = setup_mcp
    response = client.post("/mcp", headers=HEADERS, json={
        "jsonrpc": "2.0", "method": "tools/call", "params": {"name": "list_knowledge_bases"},
    })
    assert response.status_code == 202 and not response.content
    kb.list_kbs.assert_not_called()


def test_mcp_session_is_bound_to_principal_and_can_be_closed(setup_mcp):
    client, _, _ = setup_mcp
    initialized = rpc(client, "initialize", INITIALIZE, rpc_id="init")
    session_id = initialized.headers["mcp-session-id"]
    session_headers = {**HEADERS, "Mcp-Session-Id": session_id}
    assert client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).status_code == 200
    assert client.post("/mcp", headers={**HEADERS, "Mcp-Session-Id": "unknown"}, json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).status_code == 404
    assert client.delete("/mcp", headers=session_headers).status_code == 204
    assert client.post("/mcp", headers=session_headers, json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).status_code == 404


def test_mcp_session_sse_replays_notifications_and_accepts_cancellation(setup_mcp):
    client, _, _ = setup_mcp
    import app.api.controllers.mcp_routes as mcp_module

    session_id = rpc(client, "initialize", INITIALIZE, rpc_id="init").headers["mcp-session-id"]
    headers = {**HEADERS, "Mcp-Session-Id": session_id}
    assert mcp_module.publish_session_event(session_id, "notifications/message", {"text": "ready"})
    queued = mcp_module._session_events[session_id].get_nowait()
    assert "notifications/message" in queued and '"text":"ready"' in queued
    assert client.get("/mcp", headers={**headers, "Accept": "application/json"}).status_code == 406
    cancelled = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "request-1"},
    })
    assert cancelled.status_code == 202 and not cancelled.content


def test_mcp_session_cannot_be_reused_by_a_different_principal(setup_mcp, monkeypatch):
    client, _, _ = setup_mcp
    session_id = rpc(client, "initialize", INITIALIZE, rpc_id="init").headers["mcp-session-id"]
    import app.api.controllers.mcp_routes as mcp_module

    monkeypatch.setattr(mcp_module, "_principal", lambda _request: ("mcp", "other-principal"))
    assert client.post("/mcp", headers={**HEADERS, "Mcp-Session-Id": session_id}, json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}).status_code == 404


@pytest.mark.parametrize("path", ["/mcp", "/api/mcp/tools/list", "/api/mcp/tools/call"])
def test_both_endpoints_require_independent_token(setup_mcp, path):
    client, _, _ = setup_mcp
    for token in (None, "invalid"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 401


def test_origin_and_http_negotiation(setup_mcp):
    client, _, _ = setup_mcp
    assert client.post("/mcp", headers={**HEADERS, "Origin": "https://evil.example"}, json={}).status_code == 403
    assert client.post("/mcp", headers={**HEADERS, "Origin": "null"}, json={}).status_code == 403
    for path in ("/mcp", "/api/mcp/tools/list"):
        assert client.post(path, headers={**HEADERS, "Origin": config.cors_allowed_origins[0]},
                           json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 200
    assert client.get("/mcp", headers=HEADERS).status_code == 405
    assert client.delete("/mcp", headers=HEADERS).status_code == 405
    assert client.post("/mcp", headers={**HEADERS, "Content-Type": "text/plain"}, content="{}").status_code == 415
    assert client.post("/mcp", headers={**HEADERS, "Accept": "application/json"}, json={}).status_code == 406
    assert client.post("/mcp", headers={**HEADERS, "MCP-Protocol-Version": "unknown"}, json={}).status_code == 400
    malformed = client.post("/mcp", headers={**HEADERS, "Content-Type": "application/json"}, content="{")
    assert malformed.json()["error"]["code"] == -32700
    assert client.post("/mcp", headers={**HEADERS, "Content-Type": "application/json"},
                       content="x" * (1024 * 1024 + 1)).status_code == 413


def test_legacy_compatibility_and_argument_validation(setup_mcp):
    client, kb, _ = setup_mcp
    info = client.get("/api/mcp/info", headers=HEADERS).json()
    assert info["transport"] == "streamable-http" and info["endpoint"] == "/mcp"
    listed = client.post("/api/mcp/tools/call", headers=HEADERS, json={"name": "list_knowledge_bases"}).json()
    assert listed["knowledgeBases"][0]["id"] == "kb-1"
    kb.reset_mock()
    error = client.post("/api/mcp/tools/call", headers=HEADERS, json={
        "name": "search_knowledge_base", "arguments": None,
    }).json()
    assert error["isError"] is True
    kb.search_kb.assert_not_called()


def test_token_header_and_api_key_opt_in(setup_mcp, monkeypatch):
    client, _, _ = setup_mcp
    token_response = client.post("/api/mcp/tools/list", headers={"X-MCP-Token": "mcp-test-token"})
    assert token_response.status_code == 200
    from app.types.auth import AuthContext
    api_authorizer = Mock()
    api_authorizer.authenticate.return_value = AuthContext("api_key", "readonly-key")
    monkeypatch.setattr("app.api.middleware.auth.ApiKeyAuthorizer", lambda repo: api_authorizer)
    denied = client.post("/api/mcp/tools/list", headers={"Authorization": "Bearer data-key"})
    assert denied.status_code == 401
    api_authorizer.authenticate.assert_not_called()
    test_config = replace(config, auth=replace(config.auth, mcp_token="", mcp_api_key_access=True))
    monkeypatch.setattr("app.api.middleware.auth.config", test_config)
    allowed = client.post("/api/mcp/tools/list", headers={"Authorization": "Bearer data-key"})
    assert allowed.status_code == 200
    api_authorizer.authenticate.assert_called_once_with("data-key")


async def test_official_sdk_interoperability(setup_mcp):
    # Optional client integration check; the application itself needs no MCP SDK.
    pytest.importorskip("mcp")
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    client, _, _ = setup_mcp

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), headers=headers, timeout=timeout, auth=auth,
        )

    async with streamablehttp_client(
        "http://test/mcp", headers={"Authorization": "Bearer mcp-test-token"},
        httpx_client_factory=client_factory,
    ) as (read, write, _), ClientSession(read, write) as session:
        initialized = await session.initialize()
        assert initialized.protocolVersion == PROTOCOL_VERSION
        tools = await session.list_tools()
        assert len(tools.tools) == 16
        result = await session.call_tool("list_knowledge_bases", {})
        assert not result.isError and "kb-1" in result.content[0].text


def test_wiki_tools_are_listed_and_execute_read_operations():
    kb = Mock()
    wiki = Mock()
    wiki.repo.list_projects.return_value = [{"id": "wiki-1", "name": "Manual"}]
    wiki.list_pages.return_value = [{"id": "page-1", "path": "intro.md", "title": "Intro", "tags": []}]
    wiki.repo.get_page.return_value = {"id": "page-1", "path": "intro.md", "title": "Intro", "content": "hello", "tags": "[]"}
    wiki.tags.return_value = [{"tag": "python", "count": 1}]
    wiki.graph.return_value = {"nodes": [], "edges": []}
    service = McpService(kb, wiki_service=wiki)
    names = {tool["name"] for tool in service.list_tools()["tools"]}
    assert {"list_wiki_projects", "list_wiki_pages", "get_wiki_page", "get_wiki_tags", "get_wiki_graph", "ask_wiki"} <= names
    assert service.call_tool("list_wiki_projects", {})["projects"][0]["id"] == "wiki-1"
    assert service.call_tool("list_wiki_pages", {"project_id": "wiki-1", "query": "Intro"})["pages"][0]["id"] == "page-1"
    assert service.call_tool("get_wiki_tags", {"project_id": "wiki-1"})["tags"][0]["tag"] == "python"


def test_knowledge_management_tools_call_service_methods():
    kb = Mock()
    kb.create_kb.return_value = SimpleNamespace(id="kb-2", name="New")
    kb.update_kb.return_value = True
    kb.delete_kb.return_value = True
    kb.upload_doc.return_value = SimpleNamespace(id="doc-2", name="a.txt")
    kb.delete_doc.return_value = True
    kb.build_index.return_value = {"status": "ready"}
    kb.drop_index.return_value = {"status": "none"}
    kb.list_sources.return_value = [{"id": "src-1"}]
    kb.create_source.return_value = {"id": "src-2"}
    kb.delete_source.return_value = True
    service = McpService(kb)

    assert service.call_tool("create_knowledge_base", {"name": "New"})["knowledgeBase"]["id"] == "kb-2"
    assert service.call_tool("update_knowledge_base", {"kb_id": "kb-2", "name": "Edited"})["updated"]
    assert service.call_tool("delete_knowledge_base", {"kb_id": "kb-2"})["deleted"]
    uploaded = service.call_tool("upload_knowledge_document", {"kb_id": "kb-2", "filename": "a.txt", "content": "hello"})
    assert uploaded["document"]["id"] == "doc-2"
    assert service.call_tool("delete_knowledge_document", {"kb_id": "kb-2", "doc_id": "doc-2"})["deleted"]
    assert service.call_tool("build_knowledge_index", {"kb_id": "kb-2"})["result"]["status"] == "ready"
    assert service.call_tool("drop_knowledge_index", {"kb_id": "kb-2"})["result"]["status"] == "none"
    assert service.call_tool("list_knowledge_sources", {"kb_id": "kb-2"})["sources"] == [{"id": "src-1"}]
    assert service.call_tool("create_knowledge_source", {"kb_id": "kb-2", "content": "hello"})["source"]["id"] == "src-2"
    assert service.call_tool("delete_knowledge_source", {"kb_id": "kb-2", "source_id": "src-2"})["deleted"]
