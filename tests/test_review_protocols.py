"""Wire-level regressions for REVIEW-004/005/006/013."""
import json
import struct
from types import SimpleNamespace

import httpx
import pytest
from test_index_service_workflows import FakeRepository as IndexRepository
from test_proxy_service import FakeGateway, make_proxy

from app.domain.anthropic_converter import AnthropicConverter
from app.domain.entities import (
    ChannelEntity,
    DispatchResult,
    KbChunkEntity,
    ProxyRequestEntity,
)
from app.domain.gateway import GatewayService
from app.domain.index_service import HnswIndex, IndexService
from app.domain.streaming import StreamCodec
from app.infrastructure.adapters.channel_adapters import AnthropicAdapter


def frames(codec, payload):
    codec.feed_line("data: " + (payload if isinstance(payload, str) else json.dumps(payload)))
    return codec.feed_line("")


def decode(output):
    return [json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: "))) for frame in output]


@pytest.mark.parametrize("target", ["anthropic", "responses"])
def test_interleaved_text_and_parallel_fragmented_tools(target):
    codec = StreamCodec("openai", target, "chat")
    output = []
    deltas = [
        {"content": "working"},
        {"tool_calls": [{"index": 1, "id": "b", "function": {"name": "second", "arguments": '{"b":'}},
                        {"index": 0, "id": "a", "function": {"name": "first", "arguments": '{"a":'}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}, {"index": 1, "function": {"arguments": "2}"}}]},
        {"content": "done"},
    ]
    for delta in deltas:
        output += frames(codec, {"id": "r", "choices": [{"delta": delta}]})
    output += frames(codec, {"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 2, "completion_tokens": 4}})
    output += frames(codec, "[DONE]")
    events = decode(output)
    assert codec.done and not codec.failed
    if target == "responses":
        result = events[-1]["response"]
        assert result["status"] == "completed"
        calls = {item["call_id"]: item for item in result["output"] if item["type"] == "function_call"}
        assert json.loads(calls["a"]["arguments"]) == {"a": 1}
        assert json.loads(calls["b"]["arguments"]) == {"b": 2}
        assert sum(e["type"] == "response.function_call_arguments.done" for e in events) == 2
        assert result["output"][0]["content"][0]["text"] == "workingdone"
    else:
        starts = [e for e in events if e["type"] == "content_block_start"]
        assert len({e["index"] for e in starts}) == 3
        calls = {e["content_block"]["id"]: e["index"] for e in starts if e["content_block"]["type"] == "tool_use"}
        for call, expected in [("a", {"a": 1}), ("b", {"b": 2})]:
            arguments = "".join(e["delta"]["partial_json"] for e in events if e["type"] == "content_block_delta" and e["index"] == calls[call])
            assert json.loads(arguments) == expected
        assert [e["type"] for e in events[-2:]] == ["message_delta", "message_stop"]
        assert events[-2]["delta"]["stop_reason"] == "tool_use"
        assert sum(e["type"] == "content_block_stop" for e in events) == 3


def test_anthropic_tool_use_normalizes_and_round_trips_without_losing_blocks():
    upstream = {"id": "m", "content": [{"type": "text", "text": "ok"}, {"type": "tool_use", "id": "call1", "name": "f", "input": {"x": 1}}],
                "stop_reason": "tool_use", "usage": {"input_tokens": 3, "output_tokens": 4}}
    result = json.loads(AnthropicAdapter().normalize_response(json.dumps(upstream), "claude"))
    choice = result["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "ok"
    call = choice["message"]["tool_calls"][0]
    assert call["id"] == "call1" and call["function"]["name"] == "f"
    assert json.loads(call["function"]["arguments"]) == {"x": 1}
    restored = json.loads(AnthropicConverter.chat_to_messages(json.dumps(result), "claude"))
    assert restored["content"] == upstream["content"]
    assert result["usage"]["total_tokens"] == 7


def test_anthropic_request_preserves_tools_results_and_choice():
    adapter = AnthropicAdapter()
    body = {"model": "chat", "messages": [
        {"role": "system", "content": "instructions"},
        {"role": "assistant", "content": "calling", "tool_calls": [{"id": "t", "type": "function", "function": {"name": "f", "arguments": '{"x":1}'}}]},
        {"role": "tool", "tool_call_id": "t", "content": "result"}],
        "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
        "tool_choice": {"type": "function", "function": {"name": "f"}}, "stop": "END"}
    converted = adapter.prepare_body(None, ProxyRequestEntity("chat", body), "claude")
    assert converted["model"] == "claude" and converted["system"] == "instructions"
    assert converted["messages"][0]["content"][1] == {"type": "tool_use", "id": "t", "name": "f", "input": {"x": 1}}
    assert converted["messages"][1]["content"][0] == {"type": "tool_result", "tool_use_id": "t", "content": "result"}
    assert converted["tools"][0]["input_schema"] == {"type": "object"}
    assert converted["tool_choice"] == {"type": "tool", "name": "f"}
    assert converted["stop_sequences"] == ["END"]
    for original, expected in [("auto", "auto"), ("required", "any"), ("none", "none")]:
        body["tool_choice"] = original
        assert adapter.prepare_body(None, ProxyRequestEntity("chat", body), "claude")["tool_choice"] == {"type": expected}


@pytest.mark.parametrize("source,target", [(s, t) for s in ["openai", "anthropic", "ollama", "gemini"] for t in ["openai", "anthropic", "responses"]])
def test_eof_requires_protocol_terminal_evidence(source, target):
    codec = StreamCodec(source, target, "chat")
    output = codec.finish()
    assert codec.failed and codec.done
    assert "upstream_truncated" in "".join(output)
    assert "[DONE]" not in "".join(output) and "response.completed" not in "".join(output)
    assert codec.finish() == []


@pytest.mark.parametrize("target", ["openai", "responses", "anthropic", "completions"])
def test_error_event_cannot_be_followed_by_success(target):
    codec = StreamCodec("openai", target, "chat")
    output = frames(codec, {"error": {"message": "secret upstream failure"}})
    output += frames(codec, "[DONE]") + codec.finish()
    assert codec.failed and len(output) == 1
    assert "secret upstream failure" not in "".join(output)
    assert "[DONE]" not in "".join(output)


@pytest.mark.parametrize("target", ["responses", "anthropic"])
@pytest.mark.parametrize("wire", ["sse", "ndjson"])
def test_gemini_text_is_emitted_and_assembled_once(target, wire):
    codec = StreamCodec("gemini", target, "chat")
    def send(payload):
        return frames(codec, payload) if wire == "sse" else codec.feed_line(json.dumps(payload))
    output = send({"candidates": [{"content": {"parts": [{"text": "hello"}]}}]})
    output += send({"candidates": [{"content": {"parts": [{"text": " world"}]}, "finishReason": "STOP"}]})
    events = decode(output)
    assert codec.text_buffer == "hello world"
    assert codec.done and not codec.failed
    if target == "responses":
        assert events[-1]["response"]["output"][0]["content"][0]["text"] == "hello world"
    else:
        assert "".join(e["delta"]["text"] for e in events if e["type"] == "content_block_delta") == "hello world"


@pytest.mark.asyncio
async def test_truncated_gateway_attempt_and_proxy_log_are_failures():
    channel = ChannelEntity(id="c", name="test", type="openai", base_url="https://upstream.test/v1")
    dispatcher = SimpleNamespace(candidates=lambda *args: [DispatchResult(channel, "chat")])
    gateway = GatewayService(dispatcher, None)
    await gateway.aclose()
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')))
    attempts = []
    try:
        lines = [line async for line in gateway.stream(ProxyRequestEntity("chat", {"model": "chat"}), on_attempt=attempts.append)]
        assert "upstream_truncated" in "".join(lines)
        assert len(attempts) == 1 and not attempts[0].succeeded
        assert attempts[0].error_type == "upstream_stream_error"
    finally:
        await gateway.aclose()
    proxy, log = make_proxy(gateway=FakeGateway(stream_lines=lines))
    result = [c async for c in proxy.forward_stream_async('{"model":"chat"}', {})]
    assert "[DONE]" not in "".join(result)
    assert log.logs[-1].stream_status == "error"


def test_stable_index_mapping_rejects_stale_content_and_legacy_indexes(monkeypatch, tmp_path):
    monkeypatch.setattr("app.domain.index_service.INDEX_DIR", str(tmp_path))
    chunks = [KbChunkEntity(id="a", doc_id="da", content="alpha", embedding=struct.pack("<2f", 1, 0)),
              KbChunkEntity(id="b", doc_id="db", content="beta", embedding=struct.pack("<2f", 0, 1))]
    repo = IndexRepository(chunks)
    index = IndexService(repo)
    assert index.build_index("kb")["success"]
    repo.chunks = list(reversed(chunks))
    # Reopen from disk, including after an application restart.
    assert IndexService(repo).search_with_index("kb", [1, 0], 1)[0]["chunk_id"] == "a"
    repo.chunks.append(KbChunkEntity(id="added", doc_id="new", content="extra", embedding=struct.pack("<2f", 1, 0)))
    assert index.search_with_index("kb", [1, 0], 1) == []
    repo.chunks.pop()
    repo.chunks[0].content = "changed"
    assert index.search_with_index("kb", [1, 0], 1) == []
    repo.chunks = chunks[:1]
    assert index.search_with_index("kb", [1, 0], 1) == []
    legacy = HnswIndex(2)
    legacy.build([0], [[1, 0]])
    legacy.save(str(tmp_path / "kb.index"))
    assert index.search_with_index("kb", [1, 0], 1) == []


@pytest.mark.parametrize("field,value", [("chunk_map", []), ("chunk_map", {"0": []}),
    ("chunk_map", {"0": {"id": "a", "digest": 1}}), ("dataset_digest", []), ("dataset_digest", "invalid")])
def test_malformed_index_identity_is_rejected(tmp_path, field, value):
    index = HnswIndex(2)
    index.build([0], [[1, 0]])
    path = tmp_path / "malformed.index"
    index.save(str(path))
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    assert HnswIndex.load(str(path)) is None
