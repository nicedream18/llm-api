"""Policy regressions for DevBugKB BUG-20261102-001/002/003/010/011/012/015."""
import asyncio
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from anyio.to_thread import current_default_thread_limiter
from fastapi import FastAPI
from test_proxy_service import (
    FakeGateway,
    FakeQuotaRepository,
    FakeSecurityScanner,
    make_proxy,
)

from app.api.controllers import mcp_routes, routes
from app.api.middleware import auth
from app.application.errors import ApplicationError
from app.application.services.kb_service import KbService
from app.application.services.misc_services import McpService
from app.config import config
from app.domain.entities import SecurityScanResult
from app.domain.knowledge import EmbedderService, RagContextBuilder, RagService
from app.domain.model_policy import model_operation, scoped_model_call
from app.types.auth import AuthContext
from app.types.models import KbAskRequestDTO, KbSearchRequestDTO


@pytest.mark.parametrize("name", ["invoke_software_tool", "software.t.echo"])
def test_both_mcp_names_enforce_resource_acl(name):
    software, access = Mock(), Mock()
    software.list_tools.return_value = [{"id": "t", "name": "echo"}]
    access.can.side_effect = lambda ctx, kind, resource, action: kind == "mcp_tool"
    service = McpService(Mock(), access, software_service=software)
    args = {"tool_id": "t", "arguments": {"x": 1}} if name == "invoke_software_tool" else {"x": 1}
    context = AuthContext("api_key", "key")
    result = service.call_tool(name, args, context)
    assert result["isError"] and "Software tool access denied" in result["content"][0]["text"]
    software.invoke.assert_not_called()
    assert not any(t["name"].startswith("software.") for t in service.list_tools(context)["tools"])
    access.can.side_effect = None
    access.can.return_value = True
    service.call_tool(name, args, context)
    software.invoke.assert_called_once_with("t", {"x": 1}, context, False)


def _knowledge(proxy):
    embedder = EmbedderService(Mock(), None)
    retriever = Mock()
    retriever.keyword_search.return_value = [SimpleNamespace(chunk_id="c", doc_id="d", content="evidence", score=1, metadata={})]
    rag = RagService(retriever, embedder, Mock(), RagContextBuilder())
    repo = Mock()
    repo.find_kb_by_id.return_value = SimpleNamespace(embedding_model="embed")
    return KbService(repo, rag, None, embedder, proxy), embedder, retriever


@pytest.mark.parametrize("operation", ["ask", "deep_research", "search"])
def test_embedding_denial_propagates_without_keyword_fallback(operation):
    proxy, _ = make_proxy()
    service, embedder, retriever = _knowledge(proxy)
    context = AuthContext("api_key", "key", allowed_models=frozenset({"chat"}))
    request = (KbSearchRequestDTO(query="q", search_mode="vector") if operation == "search"
               else KbAskRequestDTO(question="q", model="chat"))
    try:
        with pytest.raises(ApplicationError) as error:
            getattr(service, operation)("kb", request, auth_context=context)
        assert error.value.code == "model_forbidden"
        assert proxy.gateway.requests == []
        retriever.keyword_search.assert_not_called()
    finally:
        embedder._client.close()


@pytest.mark.parametrize("deny", ["model", "channel", "quota"])
def test_kb_chat_uses_gateway_policy_and_quota(deny):
    gateway = FakeGateway()
    if deny == "channel":
        gateway._candidates = lambda *args: []
    quota = FakeQuotaRepository(reservation=None)
    proxy, _ = make_proxy(gateway=gateway, quota=quota)
    service, embedder, _ = _knowledge(proxy)
    context = AuthContext("api_key", "key", allowed_models=frozenset({"other"}) if deny == "model" else frozenset(),
                          allowed_channels=frozenset({"allowed"}) if deny == "channel" else frozenset())
    try:
        with pytest.raises(ApplicationError) as error:
            service.ask("kb", KbAskRequestDTO(question="q", model="chat", search_mode="keyword"), context)
        assert error.value.code == {"model": "model_forbidden", "channel": "channel_forbidden", "quota": "quota_exceeded"}[deny]
        assert gateway.requests == []
    finally:
        embedder._client.close()


def test_research_followup_budget_and_context_reset():
    proxy, _ = make_proxy()
    rag = RagService(None, None, None, None)
    context = AuthContext("api_key", "key", allowed_models=frozenset({"allowed"}))
    with model_operation(proxy, context) as operation:
        with pytest.raises(ApplicationError, match="Model is not allowed"):
            rag._generate_follow_up("q", "a", "forbidden")
        operation.remaining_calls = 0
        with pytest.raises(ApplicationError) as error:
            scoped_model_call({"model": "allowed", "input": "q"}, "/v1/embeddings")
        assert error.value.code == "operation_budget_exceeded"
    assert scoped_model_call({}, "/v1/embeddings") is None
    with pytest.raises(ApplicationError) as error, model_operation(None, context):
        pass
    assert error.value.code == "model_policy_unavailable"


def test_embedding_scoped_call_preserves_endpoint_and_counts_usage():
    proxy, _ = make_proxy(quota=FakeQuotaRepository())
    proxy.gateway.response.body = json.dumps({"data": [{"index": 0, "embedding": [1., 0.]}], "usage": {"total_tokens": 5}})
    embedder = EmbedderService(Mock(), None)
    context = AuthContext("api_key", "k", allowed_models=frozenset({"embed"}))
    try:
        with model_operation(proxy, context) as scope:
            assert embedder.embed("q", "embed") == [1., 0.]
            assert scope.remaining_tokens < 65536
        request = proxy.gateway.requests[0]
        assert request.endpoint == "/v1/embeddings" and request.body["input"] == ["q"]
        assert request.principal_id == "k"
        assert proxy.quota_repo.calls[-1] == ("settle", "reservation-1", 5)
    finally:
        embedder._client.close()


def test_response_redaction_reaches_client_and_log():
    safe = json.dumps({"choices": [{"message": {"content": "[REDACTED]"}}]})
    scanner = FakeSecurityScanner([SecurityScanResult(), SecurityScanResult(sanitized=True, sanitized_body=safe)])
    proxy, log = make_proxy(scanner=scanner, settings=SimpleNamespace(enabled=True, scan_response=True, fail_closed=True))
    status, result = proxy.forward('{"model":"chat"}', {})
    assert status == 200 and result == json.loads(safe)
    assert log.logs[0].response_choices == safe
    assert scanner.calls[-1][1] == "response"


@pytest.mark.parametrize("fail_closed", [False, True])
def test_response_block_cannot_be_bypassed_by_fail_open(fail_closed):
    scanner = FakeSecurityScanner([SecurityScanResult(), SecurityScanResult(blocked=True)])
    proxy, log = make_proxy(scanner=scanner, settings=SimpleNamespace(enabled=True, scan_response=True, fail_closed=fail_closed))
    status, result = proxy.forward('{"model":"chat"}', {})
    assert status == 502 and "blocked" in result["error"]["message"]
    assert log.logs[-1].response_choices is None


@pytest.mark.asyncio
async def test_response_policy_rejects_stream_before_dispatch(monkeypatch):
    proxy, _ = make_proxy(settings=SimpleNamespace(enabled=True, scan_response=True))
    chunks = [c async for c in proxy.forward_stream_async('{"model":"chat","stream":true}', {})]
    assert "stream_response_policy_unsupported" in "".join(chunks)
    assert proxy.gateway.requests == []
    app = FastAPI()
    app.include_router(routes.gateway_router)
    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(proxy_service=proxy))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/v1/responses", json={"model": "chat", "stream": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_http_dynamic_arguments_are_normalized_once(monkeypatch):
    software = Mock()
    software.invoke.return_value = {"ok": True}
    service = McpService(Mock(), software_service=software)
    monkeypatch.setattr(mcp_routes, "get_container", lambda: SimpleNamespace(mcp_service=service))
    app = FastAPI()
    app.include_router(mcp_routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/mcp", headers={"Accept": "application/json, text/event-stream"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "software.t.echo", "arguments": {"q": "raw", "nested": {"x": 1}}}})
    assert response.status_code == 200 and not response.json()["result"].get("isError")
    software.invoke.assert_called_once_with("t", {"q": "raw", "nested": {"x": 1}}, None, False)


@pytest.mark.asyncio
async def test_cancel_is_bound_to_principal_and_active_request(monkeypatch):
    started, release = threading.Event(), threading.Event()
    def call(*args):
        started.set()
        assert release.wait(5)
        return {"content": []}
    service = SimpleNamespace(validate_arguments=lambda *args: {}, call_tool=call)
    monkeypatch.setattr(mcp_routes, "get_container", lambda: SimpleNamespace(mcp_service=service))
    app = FastAPI()
    app.include_router(mcp_routes.router)
    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth_context = AuthContext("api_key", request.headers.get("x-user", "a"))
        return await call_next(request)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers={"Accept": "application/json, text/event-stream"}) as client:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo"}}
            active = asyncio.create_task(client.post("/mcp", json=payload))
            assert await asyncio.to_thread(started.wait, 2)
            duplicate = await client.post("/mcp", json=payload)
            assert duplicate.json()["error"]["code"] == -32600
            notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
            await client.post("/mcp", headers={"x-user": "b"}, json=notification)
            assert not active.done()
            release.set()
            assert (await active).json()["result"] == {"content": []}
            await client.post("/mcp", json=notification)
            assert (await client.post("/mcp", json=payload)).json()["result"] == {"content": []}
        assert not mcp_routes._running_requests
    finally:
        release.set()


@pytest.mark.asyncio
async def test_cancellation_retains_inflight_id_until_connector_finishes(monkeypatch):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def call(*args):
        started.set()
        assert release.wait(5)
        finished.set()
        return {"content": []}
    monkeypatch.setattr(mcp_routes, "get_container", lambda: SimpleNamespace(mcp_service=SimpleNamespace(validate_arguments=lambda *args: {}, call_tool=call)))
    monkeypatch.setattr(mcp_routes, "_sessions", {
        "s1": (time.monotonic() + 60, ("api_key", "a")),
        "s2": (time.monotonic() + 60, ("api_key", "a")),
    })
    app = FastAPI()
    app.include_router(mcp_routes.router)
    @app.middleware("http")
    async def identity(request, call_next):
        request.state.auth_context = AuthContext("api_key", "a")
        return await call_next(request)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers={"Accept": "application/json, text/event-stream", "Mcp-Session-Id": "s1"}) as client:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo"}}
            notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
            active = asyncio.create_task(client.post("/mcp", json=payload))
            assert await asyncio.to_thread(started.wait, 1)
            await client.post("/mcp", headers={"Mcp-Session-Id": "s2"}, json=notification)
            assert not active.done()
            await client.post("/mcp", json=notification)
            assert (await active).json()["error"]["code"] == -32800
            assert not finished.is_set()
            assert (await client.post("/mcp", json=payload)).json()["error"]["code"] == -32600
            release.set()
            assert await asyncio.to_thread(finished.wait, 1)
            for _ in range(100):
                if not mcp_routes._running_requests:
                    break
                await asyncio.sleep(0.01)
            assert not mcp_routes._running_requests and not mcp_routes._request_cancellations
    finally:
        release.set()


@pytest.mark.asyncio
async def test_tool_execution_capacity_is_bounded(monkeypatch):
    service = SimpleNamespace(validate_arguments=lambda *args: {}, call_tool=Mock())
    monkeypatch.setattr(mcp_routes, "get_container", lambda: SimpleNamespace(mcp_service=service))
    monkeypatch.setattr(mcp_routes, "MAX_ACTIVE_REQUESTS", 0)
    app = FastAPI()
    app.include_router(mcp_routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/mcp", headers={"Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo"}})
    assert response.status_code == 503
    service.call_tool.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/models", "/api/v1/kb", "/api/v1/wiki/projects", "/mcp"])
async def test_slow_authentication_does_not_block_event_loop(monkeypatch, path):
    entered, release = threading.Event(), threading.Event()
    def authenticate(*args):
        entered.set()
        assert release.wait(3)
        return AuthContext("api_key", "key")
    monkeypatch.setattr(auth.ApiKeyAuthorizer, "authenticate", authenticate)
    monkeypatch.setattr(auth, "get_container", lambda: SimpleNamespace(channel_repo=None))
    monkeypatch.setattr(auth, "config", replace(config, auth=replace(config.auth, mcp_api_key_access=True)))
    app = FastAPI()
    @app.get(path)
    async def endpoint():
        return {"ok": True}
    app.add_middleware(auth.ApiKeyAuthMiddleware)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            task = asyncio.create_task(client.get(path, headers={"Authorization": "Bearer x"}))
            assert await asyncio.to_thread(entered.wait, 1)
            assert not task.done()
            release.set()
            assert (await task).status_code == 200
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["route", "settle", "log", "usage"])
async def test_stream_database_work_leaves_event_loop_responsive(monkeypatch, stage):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(3)
        return [object()]
    proxy, _ = make_proxy(quota=FakeQuotaRepository())
    if stage == "route":
        proxy.gateway._candidates = slow
    elif stage == "settle":
        proxy.quota_repo.settle = slow
    elif stage == "log":
        proxy._record_log = slow
    else:
        proxy.usage_repo = Mock()
        monkeypatch.setattr("app.application.services.misc_services.UsageRecorder", lambda *args: SimpleNamespace(attempt=Mock(), finish=slow))
    async def collect():
        return [item async for item in proxy.forward_stream_async('{"model":"chat"}', {}, auth_context=AuthContext("api_key", "k", allowed_channels=frozenset({"c"})))]
    active = asyncio.create_task(collect())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        assert not active.done()
        await asyncio.sleep(0)
        release.set()
        assert "[DONE]" in "".join(await active)
    finally:
        release.set()
        await asyncio.gather(active, return_exceptions=True)


@pytest.mark.asyncio
async def test_authentication_thread_pool_waiting_is_bounded(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def authenticate(*args):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return AuthContext("api_key", "key")
    monkeypatch.setattr(auth.ApiKeyAuthorizer, "authenticate", authenticate)
    monkeypatch.setattr(auth, "get_container", lambda: SimpleNamespace(channel_repo=None))
    app = FastAPI()
    @app.get("/v1/models")
    def endpoint():
        return {"data": []}
    app.add_middleware(auth.ApiKeyAuthMiddleware)
    limiter = current_default_thread_limiter()
    previous = limiter.total_tokens
    limiter.total_tokens = 1
    active = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            active = [asyncio.create_task(client.get("/v1/models", headers={"Authorization": "Bearer x"})) for _ in range(3)]
            assert await asyncio.to_thread(entered.wait, 1)
            await asyncio.sleep(0.02)
            assert len(calls) == 1 and limiter.borrowed_tokens == 1
            release.set()
            assert all(response.status_code == 200 for response in await asyncio.gather(*active))
            assert len(calls) == 3
    finally:
        release.set()
        await asyncio.gather(*active, return_exceptions=True)
        limiter.total_tokens = previous


@pytest.mark.asyncio
async def test_client_disconnect_agrees_in_log_and_usage_and_retains_consumption(monkeypatch):
    quota = FakeQuotaRepository()
    proxy, log = make_proxy(quota=quota)
    recorder = SimpleNamespace(attempt=Mock(), finish=Mock())
    proxy.usage_repo = Mock()
    monkeypatch.setattr("app.application.services.misc_services.UsageRecorder", lambda *args: recorder)
    stream = proxy.forward_stream_async('{"model":"chat"}', {}, auth_context=AuthContext("api_key", "k"))
    assert "data:" in await anext(stream)
    await stream.aclose()
    assert log.logs[-1].stream_status == "client_disconnect"
    assert log.logs[-1].status_code == 499 and log.logs[-1].client_disconnect
    assert recorder.finish.call_args.args[:2] == ("client_disconnect", 499)
    assert quota.calls[-1][0] == "settle" and quota.calls[-1][2] > 0


@pytest.mark.parametrize("value", [None, [], "text", 1, True, {"model": []}, {"model": {}}, {"model": 0}])
def test_non_object_json_and_model_types_return_400(value):
    proxy, _ = make_proxy()
    assert proxy.forward(json.dumps(value), {})[0] == 400
    assert proxy.gateway.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses", "/v1/messages"])
async def test_invalid_stream_model_is_rejected_before_sse_headers(monkeypatch, path):
    proxy, _ = make_proxy()
    monkeypatch.setattr(routes, "get_container", lambda: SimpleNamespace(proxy_service=proxy))
    app = FastAPI()
    app.include_router(routes.gateway_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json={"model": [], "stream": True})
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_model"
    assert proxy.gateway.requests == []
