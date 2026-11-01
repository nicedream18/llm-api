import json

import httpx
import pytest

from app.domain.entities import ChannelEntity, ProxyRequestEntity
from app.domain.gateway import GatewayService
from app.infrastructure.adapters.channel_adapters import adapter_for, models_url
from app.infrastructure.adapters.http_adaptors import adapter_for as legacy_adapter_for


def request(body=None, endpoint="/v1/chat/completions", protocol_type="openai"):
    return ProxyRequestEntity("public-model", body or {"model": "public-model", "messages": [{"role": "user", "content": "hi"}]}, protocol_type=protocol_type, endpoint=endpoint)


def test_openai_compatible_adapter_builds_url_headers_and_model_mapping():
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1", api_key="secret")
    adapter = adapter_for(channel)
    assert adapter.build_url(channel, request()) == "https://provider.example/v1/chat/completions"
    assert legacy_adapter_for(channel) is adapter
    assert adapter.build_headers(channel, request()) == {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret",
    }
    assert adapter.prepare_body(channel, request(), "upstream-model")["model"] == "upstream-model"


def test_openai_adapter_uses_selected_upstream_key():
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1", api_key="primary")
    req = ProxyRequestEntity("m", {"model": "m"}, upstream_api_key="secondary")
    assert adapter_for(channel).build_headers(channel, req)["Authorization"] == "Bearer secondary"


@pytest.mark.parametrize("endpoint, path", [
    ("/v1/chat/completions", "/chat/completions"),
    ("/v1/completions", "/completions"),
    ("/v1/embeddings", "/embeddings"),
    ("/v1/images/generations", "/images/generations"),
    ("/v1/audio/speech", "/audio/speech"),
])
def test_openai_compatible_adapter_preserves_endpoint_family(endpoint, path):
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1")
    assert adapter_for(channel).build_url(channel, request(endpoint=endpoint)) == "https://provider.example/v1" + path


def test_responses_protocol_uses_chat_endpoint_after_conversion():
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1")
    req = request(endpoint="/v1/responses", protocol_type="responses")
    assert adapter_for(channel).build_url(channel, req) == "https://provider.example/v1/chat/completions"


def test_anthropic_public_protocol_uses_openai_compatible_upstream():
    channel = ChannelEntity(type="openai", base_url="https://provider.example/v1")
    req = request({
        "model": "public-model",
        "system": "Be concise",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "max_tokens": 8,
    }, endpoint="/v1/messages", protocol_type="anthropic")
    adapter = adapter_for(channel)
    assert adapter.build_url(channel, req) == "https://provider.example/v1/chat/completions"
    body = adapter.prepare_body(channel, req, "upstream-model")
    assert body["model"] == "upstream-model"
    assert body["messages"] == [{"role": "system", "content": "Be concise"}, {"role": "user", "content": "hi"}]


def test_anthropic_adapter_converts_chat_request_and_response():
    channel = ChannelEntity(type="claude", base_url="https://api.anthropic.com/v1", api_key="secret")
    adapter = adapter_for(channel)
    req = request({
        "model": "public-model",
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 20,
        "temperature": 0.2,
    })
    assert adapter.build_url(channel, req) == "https://api.anthropic.com/v1/messages"
    headers = adapter.build_headers(channel, req)
    assert headers["x-api-key"] == "secret"
    assert "Authorization" not in headers
    body = adapter.prepare_body(channel, req, "claude-model")
    assert body["model"] == "claude-model"
    assert body["system"] == "Be concise"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_tokens"] == 20

    normalized = json.loads(adapter.normalize_response(json.dumps({
        "id": "msg_1", "model": "claude-model", "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 4, "output_tokens": 2},
    }), "public-model"))
    assert normalized["choices"][0]["message"]["content"] == "hello"
    assert normalized["usage"]["total_tokens"] == 6


def test_ollama_native_adapter_maps_openai_options():
    channel = ChannelEntity(type="ollama", base_url="http://localhost:11434", config={"native_api": True})
    adapter = adapter_for(channel)
    req = request({
        "model": "public-model", "messages": [], "max_tokens": 32, "temperature": 0.4,
    })
    assert adapter.build_url(channel, req) == "http://localhost:11434/api/chat"
    body = adapter.prepare_body(channel, req, "llama3")
    assert body["model"] == "llama3"
    assert body["options"] == {"num_predict": 32, "temperature": 0.4}


def test_gemini_adapter_builds_native_request_and_normalizes_response():
    channel = ChannelEntity(type="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", api_key="secret")
    adapter = adapter_for(channel)
    req = request({
        "model": "public-model", "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "hello"},
        ], "max_tokens": 12, "temperature": 0.2,
    })
    req = ProxyRequestEntity(**{**req.__dict__, "stream": False, "upstream_model": "gemini-2.0-flash"})
    assert adapter.build_url(channel, req).endswith("/models/gemini-2.0-flash:generateContent")
    assert adapter.build_headers(channel, req)["x-goog-api-key"] == "secret"
    body = adapter.prepare_body(channel, req, "gemini-2.0-flash")
    assert body["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert body["systemInstruction"] == {"parts": [{"text": "Be concise"}]}
    normalized = json.loads(adapter.normalize_response(json.dumps({
        "responseId": "resp-1", "candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3, "totalTokenCount": 5},
    }), "public-model"))
    assert normalized["choices"][0]["message"]["content"] == "hi"
    assert normalized["usage"]["total_tokens"] == 5
    assert models_url(channel) == "https://generativelanguage.googleapis.com/v1beta/models"


def test_custom_adapter_honors_configured_path_and_headers():
    channel = ChannelEntity(type="custom", base_url="https://example.test/api", api_key="secret", config={"path": "/generate", "headers": {"X-Provider": "demo"}})
    adapter = adapter_for(channel)
    assert adapter.build_url(channel, request()) == "https://example.test/api/generate"
    headers = adapter.build_headers(channel, request())
    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-Provider"] == "demo"


@pytest.mark.asyncio
async def test_gateway_uses_anthropic_adapter_for_upstream_wire_request():
    channel = ChannelEntity(type="claude", base_url="https://api.anthropic.com", api_key="secret", models=["public-model"])

    class Dispatcher:
        def candidates(self, _model, _excluded=None):
            from app.domain.entities import DispatchResult
            return [DispatchResult(channel, "claude-model")]

    captured = {}

    async def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1", "model": "claude-model", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }, request=request)

    service = GatewayService(Dispatcher(), None)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await service.forward(ProxyRequestEntity("public-model", {
        "model": "public-model",
        "messages": [{"role": "system", "content": "Be concise"}, {"role": "user", "content": "hi"}],
        "max_tokens": 12,
    }))
    await service.aclose()

    assert captured["headers"]["x-api-key"] == "secret"
    assert "authorization" not in captured["headers"]
    assert captured["body"] == {
        "model": "claude-model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 12,
        "system": "Be concise",
    }
    assert json.loads(response.body)["choices"][0]["message"]["content"] == "hello"
    assert response.total_tokens == 5
