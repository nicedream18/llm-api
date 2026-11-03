"""Management workflows preserve secrets and expose real protocol behavior."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.api.controllers.routes import _stream_requested
from app.application.services.channel_dashboard import ChannelService, DashboardService
from app.application.services.provider_service import ProviderService
from app.domain.entities import ChannelApiKeyEntity, ChannelEntity, RequestLogEntity
from app.domain.gateway import GatewayService
from app.types.models import ChannelApiKeyDTO, ChannelDTO


@pytest.mark.asyncio
async def test_draft_and_individual_key_preserve_stored_credentials():
    channel = ChannelEntity(id="c", api_key="primary", api_keys=[ChannelApiKeyEntity(id="k", api_key="extra")])
    calls = []
    repo = SimpleNamespace(get_channel=lambda _: channel, get_channel_api_keys=lambda _: channel.api_keys,
                           update_channel_api_key=lambda key: calls.append(key),
                           update_channel_api_key_result=lambda *args: calls.append(args))
    async def test_channel(value):
        calls.append(value)
        return True

    gateway = SimpleNamespace(test_channel=test_channel)
    service = ChannelService(repo, gateway)
    assert (await service.test_draft_channel(ChannelDTO(id="c"))).success
    assert calls[-1].api_key == "primary"
    assert (await service.test_channel_api_key("c", "k")).success
    assert calls[-2].api_key == "extra" and calls[-2].api_keys == []
    assert channel.api_key == "primary"
    assert not (await service.test_channel_api_key("c", "absent")).success
    service.update_channel_api_key("c", "k", ChannelApiKeyDTO(name="edited"))
    assert calls[-1].api_key == "extra"


@pytest.mark.parametrize(("kind", "path", "body"), [
    ("claude", "/v1/messages", {"model": "internal", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}),
    ("gemini", "/models/internal:generateContent", {"contents": [{"role": "user", "parts": [{"text": "ping"}]}], "generationConfig": {"maxOutputTokens": 1}}),
])
@pytest.mark.asyncio
async def test_channel_probe_uses_real_adapter(kind, path, body):
    channel = ChannelEntity(type=kind, base_url="https://upstream.example", models=["public"], model_mapping={"public": "internal"})
    def handler(request):
        assert request.url.path == path
        assert json.loads(request.content) == body
        return httpx.Response(200, json={})
    gateway = GatewayService(None, None)
    await gateway.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await gateway.test_channel(channel)
    finally:
        await gateway.aclose()


@pytest.mark.parametrize(("kind", "path", "payload", "expected"), [
    ("ollama", "/api/tags", {"models": [{"name": "local"}]}, ["local"]),
    ("gemini", "/models", {"models": [{"name": "models/gemini"}]}, ["gemini"]),
])
@pytest.mark.asyncio
async def test_vendor_model_discovery(kind, path, payload, expected):
    def handler(request):
        assert request.url.path == path
        return httpx.Response(200, json=payload)
    gateway = GatewayService(None, None)
    await gateway.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await gateway.sync_models(ChannelEntity(type=kind, base_url="https://upstream.example")) == expected
    finally:
        await gateway.aclose()


@pytest.mark.parametrize(("body", "accept", "content_type", "expected"), [
    ('{"stream":false,"other":true}', "", "", False),
    ('{"stream":"true"}', "", "", False),
    ('{"stream":true}', "", "", True),
    ('{}', "text/event-stream", "", True),
    ('invalid', "text/event-stream", "", False),
    ('[]', "text/event-stream", "", False),
    ('{"stream":true}', "text/event-stream", "multipart/form-data", False),
])
def test_stream_detection_is_structural(body, accept, content_type, expected):
    assert _stream_requested(body, accept, content_type) is expected


def test_log_details_retain_execution_metadata():
    row = RequestLogEntity(id="log", request_id="execution", endpoint="/v1/messages", attempt_count=3,
                           stream_status="cancelled", usage_source="estimated", client_disconnect=True)
    dto = DashboardService(None, None)._to_dto(row)
    assert dto.request_id == "execution" and dto.attempt_count == 3
    assert dto.client_disconnect and dto.stream_status == "cancelled"


def test_model_snapshot_generation_and_freshness():
    state = {"generation": 2, "snapshots": {}}
    service = ProviderService(SimpleNamespace(synchronization_state=lambda _: state))
    assert service._discovered_models("a") is None
    snapshot = {"generation": 2, "payload": {"models": ["discovered"]}, "fetched_at": datetime.now(UTC).isoformat()}
    state["snapshots"]["models"] = snapshot
    assert service._discovered_models("a") == ["discovered"]
    snapshot["generation"] = 1
    assert service._discovered_models("a") is None
    snapshot["generation"] = 2
    snapshot["fetched_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert service._discovered_models("a") == ["discovered"]


@pytest.mark.asyncio
async def test_model_discovery_applies_channel_allowlist_to_accounts(monkeypatch):
    from app.api.controllers import routes
    from app.types.auth import AuthContext

    container = SimpleNamespace(channel_repo=SimpleNamespace(get_enabled_channels=list),
                                provider_service=SimpleNamespace(routing_channels=lambda *args, **kwargs: [ChannelEntity(id="provider:a", name="account", models=["hidden"])]))
    monkeypatch.setattr(routes, "get_container", lambda: container)
    request = SimpleNamespace(state=SimpleNamespace(auth_context=AuthContext("api_key", "k", "client", allowed_channels=frozenset({"other"}))))
    assert (await routes.models(request))["data"] == []
