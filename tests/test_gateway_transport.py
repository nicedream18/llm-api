import asyncio

import httpx
import pytest

from app.domain.entities import ChannelEntity, DispatchResult, ProxyRequestEntity
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
