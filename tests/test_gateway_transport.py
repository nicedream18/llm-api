import asyncio

import httpx
import pytest

from app.domain.entities import ChannelApiKeyEntity, ChannelEntity, DispatchResult, ProxyRequestEntity
from app.domain.gateway import GatewayService


class Dispatcher:
    def __init__(self):
        self.channels = [
            DispatchResult(ChannelEntity(id="c1", name="first", base_url="http://first", models=["demo"]), "demo"),
            DispatchResult(ChannelEntity(id="c2", name="second", base_url="http://second", models=["demo"]), "demo"),
        ]

    def candidates(self, _model, excluded=None):
        excluded = excluded or set()
        return [item for item in self.channels if item.channel.id not in excluded]


def test_retry_after_parsing_supports_delta_dates_and_clamping():
    assert GatewayService._retry_after_seconds("2", maximum=10) == 2
    assert GatewayService._retry_after_seconds("2", maximum=1) == 1
    assert GatewayService._retry_after_seconds("not-a-delay", maximum=10) == 0


def test_retry_after_http_date_is_relative_to_supplied_clock():
    import email.utils

    value = email.utils.formatdate(1_005, usegmt=True)
    assert GatewayService._retry_after_seconds(value, now=1_000, maximum=10) == 5


@pytest.mark.asyncio
async def test_gateway_switches_channel_after_503(monkeypatch):
    dispatcher = Dispatcher()
    service = GatewayService(dispatcher, None)
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        if request.url.host == "first":
            return httpx.Response(503, json={"error": "busy"}, request=request)
        return httpx.Response(200, json={"id": "ok", "usage": {"total_tokens": 3}}, request=request)

    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
    await service.aclose()
    assert response.success is True
    assert calls == ["first", "second"]
    assert [attempt.status_code for attempt in attempts] == [503, 200]


@pytest.mark.asyncio
async def test_gateway_routes_embeddings_to_embeddings_endpoint():
    channel = ChannelEntity(id="c1", name="first", base_url="http://first/v1", models=["embed"])

    class EmbeddingDispatcher:
        def candidates(self, _model, _excluded=None):
            return [DispatchResult(channel, "embed")]

    calls = []

    async def handler(request):
        calls.append((request.url.path, request.content))
        return httpx.Response(200, json={"data": [], "usage": {"total_tokens": 1}}, request=request)

    service = GatewayService(EmbeddingDispatcher(), None)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await service.forward(ProxyRequestEntity(
        "embed", {"model": "embed", "input": ["hello"]}, endpoint="/v1/embeddings"
    ))
    await service.aclose()
    assert response.success
    assert calls[0][0] == "/v1/embeddings"


@pytest.mark.asyncio
async def test_gateway_does_not_retry_400(monkeypatch):
    dispatcher = Dispatcher()
    service = GatewayService(dispatcher, None)
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad"}, request=request)

    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
    await service.aclose()
    assert response.status_code == 400
    assert calls == 1
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_gateway_cools_down_retryable_channel(monkeypatch):
    dispatcher = Dispatcher()
    service = GatewayService(dispatcher, None)
    calls = []

    async def no_backoff(_attempt_no, _retry_after):
        return None

    monkeypatch.setattr(service, "_backoff_with_hint", no_backoff)

    async def handler(request):
        calls.append(request.url.host)
        return httpx.Response(503, headers={"Retry-After": "1"}, json={"error": "busy"}, request=request)

    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
    await service.aclose()
    assert response.status_code == 503
    assert len(attempts) == 2
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_gateway_fails_over_to_second_channel_key(monkeypatch):
    key_one = ChannelApiKeyEntity(id="k1", api_key="one", weight=1)
    key_two = ChannelApiKeyEntity(id="k2", api_key="two", weight=1)
    channel = ChannelEntity(id="c1", name="one-channel", base_url="http://one", models=["demo"], api_keys=[key_one, key_two])

    class SingleDispatcher:
        def candidates(self, _model, _excluded=None):
            return [DispatchResult(channel, "demo")]

    calls = []

    async def handler(request):
        calls.append(request.headers.get("authorization"))
        if request.headers.get("authorization") == "Bearer one":
            return httpx.Response(503, json={"error": "busy"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    service = GatewayService(SingleDispatcher(), None)
    monkeypatch.setattr(service, "_select_api_key", lambda _channel: ("one", "k1") if not calls else ("two", "k2"))
    monkeypatch.setattr(service, "_backoff_with_hint", lambda *_args: asyncio.sleep(0))
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
    await service.aclose()
    assert response.success is True
    assert calls == ["Bearer one", "Bearer two"]
    assert len(attempts) == 2


def test_channel_test_targets_the_passed_channel():
    service = GatewayService(Dispatcher(), None)
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"ok": True}, request=request)

    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    selected = ChannelEntity(
        id="selected", name="selected", base_url="http://selected", models=["demo"]
    )
    assert service.test_channel(selected)
    assert calls == ["selected"]
    asyncio.run(service.aclose())
