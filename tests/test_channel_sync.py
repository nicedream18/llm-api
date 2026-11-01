import asyncio

import httpx

from app.domain.entities import ChannelEntity
from app.domain.gateway import GatewayService


def test_gateway_sync_models_reads_openai_models_endpoint():
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1", api_key="secret")
    calls = []

    async def handler(request):
        calls.append((request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json={"data": [{"id": "gpt-x"}, {"id": "gpt-x"}, {"id": "embed-x"}]}, request=request)

    service = GatewayService(None, None)
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert service.sync_models(channel) == ["gpt-x", "embed-x"]
    finally:
        asyncio.run(service.aclose())
    assert calls == [("/v1/models", "Bearer secret")]


def test_gateway_sync_models_accepts_plain_list_payload():
    channel = ChannelEntity(type="openai", base_url="https://provider.example")

    async def handler(request):
        return httpx.Response(200, json=["alpha", {"id": "beta"}], request=request)

    service = GatewayService(None, None)
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert service.sync_models(channel) == ["alpha", "beta"]
    finally:
        asyncio.run(service.aclose())
