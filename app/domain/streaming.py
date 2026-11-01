"""Streaming protocol primitives used by the gateway.

The public API is SSE based, but upstream providers do not all use the same
event names or payloads.  This module keeps the wire parser independent from
the gateway retry code and exposes a small stateful codec for one stream.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SSEEvent:
    """One server-sent event after field folding."""

    data: str = ""
    event: str | None = None
    event_id: str | None = None
    retry: int | None = None


class SSEDecoder:
    """Incrementally decode SSE lines, including multiline ``data`` fields."""

    def __init__(self) -> None:
        self._event: str | None = None
        self._event_id: str | None = None
        self._retry: int | None = None
        self._data: list[str] = []

    def feed_line(self, line: str) -> SSEEvent | None:
        line = str(line).rstrip("\r")
        if line == "":
            return self._flush()
        if line.startswith(":"):
            return None

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "id" and "\x00" not in value:
            self._event_id = value
        elif field == "retry":
            try:
                retry = int(value)
            except ValueError:
                retry = None
            if retry is not None and retry >= 0:
                self._retry = retry
        elif field == "data":
            self._data.append(value)
        return None

    def finish(self) -> SSEEvent | None:
        """Flush a final event when the upstream closes without a blank line."""
        return self._flush()

    def _flush(self) -> SSEEvent | None:
        if not self._data and self._event is None and self._event_id is None and self._retry is None:
            return None
        event = SSEEvent(
            data="\n".join(self._data),
            event=self._event,
            event_id=self._event_id,
            retry=self._retry,
        )
        self._event = None
        self._event_id = None
        self._retry = None
        self._data = []
        return event


def encode_sse(event: SSEEvent) -> str:
    """Serialize an event with a canonical SSE field order."""
    fields: list[str] = []
    if event.event_id is not None:
        fields.append(f"id: {event.event_id}")
    if event.event is not None:
        fields.append(f"event: {event.event}")
    if event.retry is not None:
        fields.append(f"retry: {event.retry}")
    data_lines = event.data.split("\n") if event.data != "" else [""]
    fields.extend(f"data: {line}" for line in data_lines)
    return "\n".join(fields) + "\n\n"


def _json(data: str) -> dict[str, Any] | None:
    try:
        value = json.loads(data)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _usage(payload: dict[str, Any]) -> dict[str, int] | None:
    value = payload.get("usage") or payload.get("usageMetadata")
    if not isinstance(value, dict):
        return None
    input_tokens = int(value.get("prompt_tokens", value.get("input_tokens", value.get("promptTokenCount", 0))) or 0)
    output_tokens = int(value.get("completion_tokens", value.get("output_tokens", value.get("candidatesTokenCount", 0))) or 0)
    total = int(value.get("total_tokens", value.get("totalTokenCount", input_tokens + output_tokens)) or input_tokens + output_tokens)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}


def usage_from_payload(payload: str | dict[str, Any]) -> dict[str, int] | None:
    """Extract normalized usage from an SSE JSON data payload."""
    if isinstance(payload, str):
        value = _json(payload)
    else:
        value = payload if isinstance(payload, dict) else None
    return _usage(value) if value is not None else None


def _merge_usage(current: dict[str, int] | None, update: dict[str, int] | None) -> dict[str, int] | None:
    if not current:
        return update
    if not update:
        return current
    merged = {key: max(int(current.get(key, 0)), int(update.get(key, 0))) for key in ("input_tokens", "output_tokens", "total_tokens")}
    merged["total_tokens"] = max(merged["total_tokens"], merged["input_tokens"] + merged["output_tokens"])
    return merged


def _openai_chunk(delta: dict[str, Any], *, model: str, finish_reason: str | None = None, usage: dict[str, int] | None = None, response_id: str | None = None) -> dict[str, Any]:
    chunk: dict[str, Any] = {
        "id": response_id or f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = {
            "prompt_tokens": usage["input_tokens"],
            "completion_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
        }
    return chunk


def _event(data: dict[str, Any], event_name: str | None = None) -> str:
    return encode_sse(SSEEvent(data=json.dumps(data, ensure_ascii=False, separators=(",", ":")), event=event_name))


class StreamCodec:
    """Convert one upstream stream to the requested public protocol."""

    def __init__(self, source_protocol: str = "openai", target_protocol: str = "openai", model: str = "") -> None:
        self.source_protocol = source_protocol.lower()
        self.target_protocol = target_protocol.lower()
        self.model = model
        self.decoder = SSEDecoder()
        self.response_id: str | None = None
        self.done = False
        self.started = False
        self.text_started = False
        self.text_buffer = ""
        self.tool_blocks: dict[int, int] = {}
        self.usage: dict[str, int] | None = None

    def feed_line(self, line: str) -> list[str]:
        """Consume one upstream line and return zero or more complete events."""
        raw = str(line).rstrip("\r")
        if self.source_protocol in {"ollama", "gemini"} and not raw.startswith(("data:", "event:", "id:", "retry:", ":")):
            if not raw:
                return []
            direct_event = SSEEvent(data=raw)
            return self._convert(direct_event)
        decoded_event: SSEEvent | None = self.decoder.feed_line(raw)
        return self._convert(decoded_event) if decoded_event else []

    def finish(self) -> list[str]:
        output: list[str] = []
        event = self.decoder.finish()
        if event:
            output.extend(self._convert(event))
        if not self.done:
            output.extend(self._finish_protocol())
        return output

    def _convert(self, event: SSEEvent) -> list[str]:
        payload = event.data.strip()
        if payload == "":
            return []
        if self.source_protocol == "anthropic":
            return self._anthropic_to_target(event)
        if self.source_protocol == "gemini":
            return self._gemini_to_target(event)
        if self.source_protocol == "ollama":
            return self._ollama_to_target(event)
        if payload == "[DONE]":
            return self._finish_protocol()
        data = _json(payload)
        if data is None:
            return [encode_sse(event)] if self.target_protocol == "openai" else []
        self.response_id = self.response_id or data.get("id")
        usage = _usage(data)
        if usage:
            self.usage = _merge_usage(self.usage, usage)
        return self._emit_openai_payload(data, event.event, event.event_id)

    def _emit_openai_payload(self, payload: dict[str, Any], event_name: str | None = None, event_id: str | None = None) -> list[str]:
        """Route an OpenAI-shaped chunk to the requested public protocol."""
        if self.target_protocol == "openai":
            return [encode_sse(SSEEvent(data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")), event=event_name, event_id=event_id))]
        if self.target_protocol == "anthropic":
            return self._openai_to_anthropic(payload)
        if self.target_protocol == "responses":
            return self._openai_to_responses(payload)
        if self.target_protocol == "completions":
            return self._openai_to_completions(payload)
        return [encode_sse(SSEEvent(data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")), event=event_name, event_id=event_id))]

    def _anthropic_to_target(self, event: SSEEvent) -> list[str]:
        payload = _json(event.data)
        if payload is None:
            return []
        event_type = str(payload.get("type") or event.event or "")
        reported_usage = _usage(payload.get("message", {}) if event_type == "message_start" else payload)
        if reported_usage:
            self.usage = _merge_usage(self.usage, reported_usage)
        if self.target_protocol == "anthropic":
            if event_type == "message_stop":
                self.done = True
            return [encode_sse(event)]
        self.response_id = self.response_id or (payload.get("message") or {}).get("id")
        if event_type in {"ping", "message_start"}:
            return []
        if event_type == "content_block_start":
            block = payload.get("content_block") or {}
            if block.get("type") == "text":
                return self._emit_openai_payload(_openai_chunk({"role": "assistant"}, model=self.model, response_id=self.response_id))
            if block.get("type") == "tool_use":
                index = int(payload.get("index", 0))
                self.tool_blocks[index] = index
                delta = {"tool_calls": [{"index": index, "id": block.get("id"), "type": "function", "function": {"name": block.get("name", ""), "arguments": ""}}]}
                return self._emit_openai_payload(_openai_chunk(delta, model=self.model, response_id=self.response_id))
            return []
        if event_type == "content_block_delta":
            delta = payload.get("delta") or {}
            if delta.get("type") == "text_delta":
                self.text_started = True
                return self._emit_openai_payload(_openai_chunk({"content": delta.get("text", "")}, model=self.model, response_id=self.response_id))
            if delta.get("type") == "input_json_delta":
                index = int(payload.get("index", 0))
                tool_delta = {"tool_calls": [{"index": index, "function": {"arguments": delta.get("partial_json", "")}}]}
                return self._emit_openai_payload(_openai_chunk(tool_delta, model=self.model, response_id=self.response_id))
            return []
        if event_type == "message_delta":
            message_delta = payload.get("delta") or {}
            stop = message_delta.get("stop_reason")
            stop_key = stop if isinstance(stop, str) else None
            stop_map: dict[str, str] = {
                "end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop", "tool_use": "tool_calls",
            }
            finish = stop_map.get(stop_key) if stop_key else None
            if finish is None:
                finish = stop_key
            chunk = _openai_chunk({}, model=self.model, finish_reason=finish, usage=self.usage, response_id=self.response_id)
            return self._emit_openai_payload(chunk)
        if event_type == "message_stop":
            return self._finish_protocol()
        return []

    def _gemini_to_target(self, event: SSEEvent) -> list[str]:
        payload = _json(event.data)
        if payload is None:
            return []
        usage = _usage(payload)
        if usage:
            self.usage = _merge_usage(self.usage, usage)
        candidates = payload.get("candidates") or []
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        output: list[str] = []
        if text:
            self.text_buffer += text
            output.extend(self._emit_openai_payload(_openai_chunk({"content": text}, model=self.model, response_id=self.response_id)))
        reason = candidate.get("finishReason")
        if reason:
            output.extend(self._emit_openai_payload(_openai_chunk({}, model=self.model, finish_reason=str(reason).lower(), usage=self.usage, response_id=self.response_id)))
            output.extend(self._finish_protocol())
        return output

    def _ollama_to_target(self, event: SSEEvent) -> list[str]:
        payload = _json(event.data)
        if payload is None:
            return []
        input_tokens = int(payload.get("prompt_eval_count", 0) or 0)
        output_tokens = int(payload.get("eval_count", 0) or 0)
        if input_tokens or output_tokens:
            self.usage = _merge_usage(self.usage, {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens})
        message = payload.get("message") or {}
        output: list[str] = []
        if message.get("role"):
            output.extend(self._emit_openai_payload(_openai_chunk({"role": message["role"]}, model=self.model, response_id=self.response_id)))
        if message.get("content"):
            output.extend(self._emit_openai_payload(_openai_chunk({"content": message["content"]}, model=self.model, response_id=self.response_id)))
        if payload.get("done"):
            output.extend(self._emit_openai_payload(_openai_chunk({}, model=self.model, finish_reason="stop", usage=self.usage, response_id=self.response_id)))
            output.extend(self._finish_protocol())
        return output

    def _openai_to_anthropic(self, payload: dict[str, Any]) -> list[str]:
        output: list[str] = []
        if not self.started:
            self.started = True
            output.append(_event({"type": "message_start", "message": {"id": self.response_id or f"msg_{uuid.uuid4().hex}", "type": "message", "role": "assistant", "content": [], "model": self.model, "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}))
        choices = payload.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            output.append(_event({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}) if not self.text_started else "")
            self.text_started = True
            self.text_buffer += content
            output.append(_event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": content}}))
        finish = choice.get("finish_reason")
        if finish:
            stop = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}.get(finish, finish)
            output.append(_event({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": (self.usage or {}).get("output_tokens", 0)}}))
        return [item for item in output if item]

    def _openai_to_responses(self, payload: dict[str, Any]) -> list[str]:
        output: list[str] = []
        if not self.started:
            self.started = True
            self.response_id = self.response_id or f"resp_{uuid.uuid4().hex}"
            output.append(_event({"type": "response.created", "response": {"id": self.response_id, "object": "response", "status": "in_progress", "model": self.model, "output": []}}, "response.created"))
        choices = payload.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        delta = choice.get("delta") or {}
        if delta.get("content"):
            self.text_buffer += delta["content"]
            output.append(_event({"type": "response.output_text.delta", "response_id": self.response_id, "item_id": f"msg_{self.response_id}", "output_index": 0, "content_index": 0, "delta": delta["content"]}, "response.output_text.delta"))
        finish = choice.get("finish_reason")
        if finish:
            output.append(_event({"type": "response.output_text.done", "response_id": self.response_id, "item_id": f"msg_{self.response_id}", "output_index": 0, "content_index": 0, "text": self.text_buffer}, "response.output_text.done"))
        return output

    def _openai_to_completions(self, payload: dict[str, Any]) -> list[str]:
        choices: list[dict[str, Any]] = []
        for choice in payload.get("choices") or []:
            delta = choice.get("delta") or {}
            choices.append({
                "index": choice.get("index", len(choices)),
                "text": delta.get("content") or "",
                "logprobs": None,
                "finish_reason": choice.get("finish_reason"),
            })
        result = {
            "id": payload.get("id") or self.response_id,
            "object": "text_completion",
            "created": payload.get("created"),
            "model": payload.get("model") or self.model,
            "choices": choices,
        }
        if payload.get("usage"):
            result["usage"] = payload["usage"]
        return [encode_sse(SSEEvent(data=json.dumps(result, ensure_ascii=False, separators=(",", ":"))))]

    def _finish_protocol(self) -> list[str]:
        if self.done:
            return []
        self.done = True
        if self.target_protocol == "anthropic":
            output = []
            if self.started:
                output.append(_event({"type": "message_stop"}))
            return output
        if self.target_protocol == "responses":
            return [_event({"type": "response.completed", "response": {"id": self.response_id or f"resp_{uuid.uuid4().hex}", "object": "response", "status": "completed", "model": self.model, "usage": self.usage}}, "response.completed")]
        return [encode_sse(SSEEvent(data="[DONE]"))]
