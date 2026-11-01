import json

import httpx
import pytest

from app.domain.entities import ChannelEntity, DispatchResult, ProxyRequestEntity
from app.domain.gateway import GatewayService
from app.domain.streaming import SSEDecoder, SSEEvent, StreamCodec, encode_sse


def _payload(frame: str) -> dict:
    data = next(line[6:] for line in frame.splitlines() if line.startswith("data: "))
    return json.loads(data)


def test_sse_decoder_folds_multiline_data_and_flushes_at_eof():
    decoder = SSEDecoder()
    assert decoder.feed_line("event: message") is None
    assert decoder.feed_line("id: 7") is None
    assert decoder.feed_line("data: first") is None
    assert decoder.feed_line("data: second") is None
    event = decoder.feed_line("")
    assert event == SSEEvent(data="first\nsecond", event="message", event_id="7")
    assert decoder.feed_line("data: tail") is None
    assert decoder.finish() == SSEEvent(data="tail")


def test_encode_sse_preserves_control_fields():
    assert encode_sse(SSEEvent(data="a\nb", event="delta", event_id="x", retry=100)) == (
        "id: x\nevent: delta\nretry: 100\ndata: a\ndata: b\n\n"
    )


def test_anthropic_stream_is_converted_to_openai_chunks_and_usage():
    codec = StreamCodec("anthropic", "openai", "claude-3")
    lines = [
        'event: message_start',
        'data: {"type":"message_start","message":{"id":"msg_1","usage":{"input_tokens":4}}}',
        "",
        'event: content_block_start',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "",
        'event: content_block_delta',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}',
        "",
        'event: message_delta',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
        "",
        'event: message_stop',
        'data: {"type":"message_stop"}',
        "",
    ]
    frames = [frame for line in lines for frame in codec.feed_line(line)]
    assert _payload(frames[0])["choices"][0]["delta"]["role"] == "assistant"
    assert _payload(frames[1])["choices"][0]["delta"]["content"] == "hello"
    final = _payload(frames[2])
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["usage"] == {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    assert frames[-1] == "data: [DONE]\n\n"


def test_openai_stream_is_converted_to_responses_events():
    codec = StreamCodec("openai", "responses", "gpt-test")
    frames = []
    for line in [
        'data: {"id":"chat_1","model":"gpt-test","choices":[{"delta":{"content":"hi"},"finish_reason":null}]}',
        "",
        'data: {"id":"chat_1","model":"gpt-test","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}',
        "",
        "data: [DONE]",
        "",
    ]:
        frames.extend(codec.feed_line(line))
    assert [next(line[7:] for line in frame.splitlines() if line.startswith("event: ")) for frame in frames[:2]] == ["response.created", "response.output_text.delta"]
    assert _payload(frames[1])["delta"] == "hi"
    assert next(line[7:] for line in frames[-1].splitlines() if line.startswith("event: ")) == "response.completed"


def test_gemini_json_stream_is_converted_to_openai():
    codec = StreamCodec("gemini", "openai", "gemini-2")
    frames = codec.feed_line('{"responseId":"r1","candidates":[{"content":{"parts":[{"text":"hello"}]}}],"usageMetadata":{"promptTokenCount":2,"candidatesTokenCount":3,"totalTokenCount":5}}')
    assert _payload(frames[0])["choices"][0]["delta"]["content"] == "hello"
    assert codec.usage == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}


def test_ollama_native_json_stream_is_converted_to_openai():
    codec = StreamCodec("ollama", "openai", "llama3")
    frames = codec.feed_line('{"model":"llama3","message":{"role":"assistant","content":"hi"},"done":false}')
    frames += codec.feed_line('{"model":"llama3","done":true,"prompt_eval_count":2,"eval_count":3}')
    assert _payload(frames[0])["choices"][0]["delta"]["role"] == "assistant"
    assert _payload(frames[1])["choices"][0]["delta"]["content"] == "hi"
    assert _payload(frames[2])["usage"]["total_tokens"] == 5
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_gateway_converts_anthropic_stream_before_returning_lines():
    channel = ChannelEntity(type="claude", base_url="https://api.anthropic.com", api_key="secret", models=["public"])

    class Dispatcher:
        def candidates(self, _model, _excluded=None):
            return [DispatchResult(channel, "claude-model")]

    body = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"id":"msg_1","usage":{"input_tokens":1}}}\n\n'
        "event: content_block_delta\n"
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\n'
        "event: message_stop\n"
        'data: {"type":"message_stop"}\n\n'
    )

    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode(), request=request)

    service = GatewayService(Dispatcher(), None)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = [line async for line in service.stream(ProxyRequestEntity("public", {"model": "public"}))]
    await service.aclose()
    assert any('"content":"ok"' in line for line in result)
    assert result[-1] == ""
