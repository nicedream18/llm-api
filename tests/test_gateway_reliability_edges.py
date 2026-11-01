import asyncio

import httpx
import pytest

from app.domain.entities import ChannelEntity, DispatchResult, ProxyRequestEntity
from app.domain.gateway import GatewayService


class StaticDispatcher:
    def __init__(self, *channels):
        self.channels = list(channels)

    def candidates(self, _model, excluded=None):
        excluded = excluded or set()
        return [candidate for candidate in self.channels if candidate.channel.id not in excluded]


def _candidate(channel, model="demo"):
    return DispatchResult(channel, model)


@pytest.mark.asyncio
async def test_forward_returns_clean_unavailable_response_when_no_candidate():
    service = GatewayService(StaticDispatcher(), None)
    try:
        response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
        assert response.status_code == 503
        assert response.error_message == "No available upstream channel"
        assert attempts == []
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_forward_sanitizes_network_error_and_updates_channel_health(monkeypatch):
    channel = ChannelEntity(id="c1", name="channel", base_url="https://upstream.example", models=["demo"])
    service = GatewayService(StaticDispatcher(_candidate(channel)), None)
    updates = []

    class ChannelRepository:
        def update_test_result(self, channel_id, success):
            updates.append((channel_id, success))

    service.channel_repository = ChannelRepository()

    async def no_backoff(*_args):
        return None

    async def fail_request(*_args, **_kwargs):
        request = httpx.Request("POST", "https://upstream.example")
        raise httpx.ConnectError("secret credentials leaked by transport", request=request)

    monkeypatch.setattr(service, "_backoff_with_hint", no_backoff)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(fail_request))
    try:
        response, attempts = await service.forward_with_attempts(ProxyRequestEntity("demo", {"model": "demo"}))
    finally:
        await service.aclose()

    assert response.status_code == 502
    assert response.error_message == "upstream connection failed"
    assert "secret credentials" not in response.error_message
    assert len(attempts) == 1 and attempts[0].error_type == "ConnectError"
    assert attempts[0].error_message == "upstream connection failed"
    assert updates == [("c1", False)]
    assert service._is_cooled(channel)


@pytest.mark.asyncio
async def test_forward_respects_api_key_channel_allowlist():
    allowed = ChannelEntity(id="allowed", name="allowed", base_url="https://allowed.example", models=["demo"])
    denied = ChannelEntity(id="denied", name="denied", base_url="https://denied.example", models=["demo"])
    service = GatewayService(StaticDispatcher(_candidate(denied), _candidate(allowed)), None)
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json={"ok": True}, request=request)

    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await service.forward(ProxyRequestEntity(
            "demo", {"model": "demo"}, allowed_channels=frozenset({"allowed"}),
        ))
    finally:
        await service.aclose()
    assert result.success and calls == ["allowed.example"]


@pytest.mark.asyncio
async def test_stream_retries_connect_failure_before_first_event(monkeypatch):
    first = ChannelEntity(id="first", name="first", base_url="https://first.example", models=["demo"])
    second = ChannelEntity(id="second", name="second", base_url="https://second.example", models=["demo"])
    service = GatewayService(StaticDispatcher(_candidate(first), _candidate(second)), None)
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        if request.url.host == "first.example":
            raise httpx.ConnectError("private transport detail", request=request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: {\"ok\":true}\n\ndata: [DONE]\n\n", request=request)

    async def no_backoff(*_args):
        return None

    monkeypatch.setattr(service, "_backoff", no_backoff)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        frames = [frame async for frame in service.stream(ProxyRequestEntity("demo", {"model": "demo", "stream": True}))]
    finally:
        await service.aclose()

    assert calls == ["first.example", "second.example"]
    assert any('"ok":true' in line for line in frames)
    assert "data: [DONE]" in frames


class InterruptedBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"data: {\"partial\":true}\n\n"
        raise httpx.RemoteProtocolError("connection ended mid-event")

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_emitting_partial_content():
    channel = ChannelEntity(id="c1", name="channel", base_url="https://upstream.example", models=["demo"])
    service = GatewayService(StaticDispatcher(_candidate(channel)), None)
    calls = []

    async def handler(request):
        calls.append(request.url.host)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=InterruptedBody(), request=request,
        )

    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stream = service.stream(ProxyRequestEntity("demo", {"model": "demo", "stream": True}))
    try:
        assert '"partial":true' in await anext(stream)
        # The codec yields the frame's line and its terminating blank line separately.
        assert await anext(stream) == ""
        with pytest.raises(RuntimeError, match="upstream stream connection failed"):
            await anext(stream)
    finally:
        await stream.aclose()
        await service.aclose()
    assert calls == ["upstream.example"]


def test_gateway_token_extraction_and_response_header_filtering():
    from app.domain.gateway import _extract_tokens, _response_headers

    assert _extract_tokens(b"binary") == (0, 0, 0)
    assert _extract_tokens("not-json") == (0, 0, 0)
    assert _extract_tokens('{"usage":{"input_tokens":3,"output_tokens":4}}') == (3, 4, 7)
    response = httpx.Response(200, headers={
        "content-type": "application/json", "content-disposition": "inline",
        "x-private": "secret", "etag": "tag",
    })
    assert _response_headers(response) == {
        "content-type": "application/json", "content-disposition": "inline", "etag": "tag",
    }


def test_sync_model_discovery_deduplicates_and_rejects_invalid_payloads():
    channel = ChannelEntity(id="c1", name="channel", base_url="https://upstream.example", models=[])
    service = GatewayService(StaticDispatcher(), None)

    async def handler(request):
        return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-a"}, "model-b", {"id": " "}]}, request=request)

    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert service.sync_models(channel) == ["model-a", "model-b"]
    finally:
        asyncio.run(service.aclose())

    async def invalid_handler(request):
        return httpx.Response(200, json={"data": "not-a-list"}, request=request)

    service.client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_handler))
    try:
        with pytest.raises(TypeError, match="not a list"):
            service.sync_models(channel)
    finally:
        asyncio.run(service.aclose())
