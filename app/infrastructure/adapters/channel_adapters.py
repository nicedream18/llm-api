"""Channel specific HTTP request and response behavior.

The gateway owns routing and retry policy.  Adapters own the wire contract for
an individual upstream family so that adding a provider does not grow another
branch in the gateway itself.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


def _join(base_url: str | None, path: str) -> str:
    """Join a provider base URL and path without creating duplicate slashes."""
    base = (base_url or "").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _copy_headers(config: dict[str, Any] | None) -> dict[str, str]:
    headers = (config or {}).get("headers")
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items()}


def _endpoint_path(request) -> str:
    """Map an incoming public endpoint to a provider-relative API path."""
    endpoint = str(getattr(request, "endpoint", "") or "")
    if endpoint.startswith("/v1/"):
        endpoint = endpoint[3:]
    elif endpoint.startswith("/"):
        endpoint = endpoint[1:]
    return "/" + endpoint if endpoint else "/chat/completions"


class ChannelAdapter(ABC):
    """Wire-level contract used by :class:`GatewayService`."""

    @abstractmethod
    def build_url(self, channel, request) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_headers(self, channel, request) -> dict[str, str]:
        raise NotImplementedError

    def prepare_body(self, channel, request, upstream_model: str) -> dict[str, Any]:
        body = dict(request.body)
        if getattr(request, "protocol_type", "") == "anthropic":
            from app.domain.anthropic_converter import AnthropicConverter

            body = json.loads(AnthropicConverter.messages_to_openai(json.dumps(body, ensure_ascii=False)))
        body["model"] = upstream_model
        return body

    def prepare_raw_body(self, channel, request, upstream_model: str) -> bytes | None:
        """Prepare a non-JSON request while preserving uploaded file bytes."""
        if request.raw_body is None:
            return None
        from app.domain.multipart import replace_model

        return replace_model(request.raw_body, request.model, upstream_model)

    def normalize_response(self, body: str, model: str) -> str:
        """Return an OpenAI-compatible response body when conversion is needed."""
        return body

    def stream_protocol(self, channel) -> str:
        """Identify the provider's streaming wire format."""
        return "openai"


class OpenAICompatibleAdapter(ChannelAdapter):
    def build_url(self, channel, request) -> str:
        configured_path = (channel.config or {}).get("path")
        if configured_path:
            path = str(configured_path)
        elif getattr(request, "protocol_type", "") in {"responses", "anthropic", "completions"}:
            # Non-OpenAI public requests are converted before the compatible
            # upstream call, so use the Chat Completions endpoint.
            path = "/chat/completions"
        else:
            path = _endpoint_path(request)
        return _join(channel.base_url, str(path))

    def build_headers(self, channel, request) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(request, "upstream_api_key", None)
        if api_key is None:
            api_key = channel.api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(_copy_headers(channel.config))
        return headers


class AnthropicAdapter(ChannelAdapter):
    def stream_protocol(self, channel) -> str:
        return "anthropic"

    def build_url(self, channel, request) -> str:
        base = (channel.base_url or "").rstrip("/")
        path = "/messages" if base.endswith("/v1") else "/v1/messages"
        return _join(base, path)

    def build_headers(self, channel, request) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": str((channel.config or {}).get("anthropic_version", "2023-06-01")),
        }
        api_key = getattr(request, "upstream_api_key", None)
        if api_key is None:
            api_key = channel.api_key
        if api_key:
            headers["x-api-key"] = api_key
        headers.update(_copy_headers(channel.config))
        return headers

    def prepare_body(self, channel, request, upstream_model: str) -> dict[str, Any]:
        source = dict(request.body)
        if getattr(request, "protocol_type", "") == "anthropic":
            source["model"] = upstream_model
            return source
        messages = source.pop("messages", [])
        system: list[Any] = []
        anthropic_messages: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "system":
                system.append(content)
                continue
            if role == "tool":
                anthropic_messages.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": content,
                }]})
                continue
            calls = message.get("tool_calls") or []
            if calls:
                blocks = [{"type": "text", "text": content}] if content else []
                for call in calls:
                    function = call.get("function") or {}
                    arguments = function.get("arguments", "{}")
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise TypeError("Tool arguments must be a JSON object")
                    blocks.append({"type": "tool_use", "id": call["id"],
                                   "name": function["name"], "input": arguments})
                content = blocks
            anthropic_messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})

        body: dict[str, Any] = {
            "model": upstream_model,
            "messages": anthropic_messages,
            "max_tokens": source.pop("max_tokens", source.pop("max_output_tokens", 4096)),
        }
        if system:
            body["system"] = "\n\n".join(str(item) for item in system)
        for key in ("temperature", "top_p", "stop_sequences", "stream"):
            if key in source:
                body[key] = source[key]
        if "stop" in source:
            body["stop_sequences"] = [source["stop"]] if isinstance(source["stop"], str) else source["stop"]
        if source.get("tools"):
            body["tools"] = [{"name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                for t in source["tools"] if t.get("type") == "function"]
        choice = source.get("tool_choice")
        if isinstance(choice, dict):
            body["tool_choice"] = {"type": "tool", "name": choice["function"]["name"]}
        elif choice in {"auto", "required", "none"}:
            body["tool_choice"] = {"type": {"required": "any"}.get(choice, choice)}
        return body

    def normalize_response(self, body: str, model: str) -> str:
        """Convert a non-streaming Anthropic message into Chat Completions."""
        try:
            response = json.loads(body)
        except (TypeError, ValueError):
            return body
        if not isinstance(response, dict):
            return body
        content = response.get("content") or []
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        tool_calls = [{"id": item["id"], "type": "function", "function": {
            "name": item["name"], "arguments": json.dumps(item.get("input", {}), ensure_ascii=False)
        }} for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        usage = response.get("usage") or {}
        finish = str(response.get("stop_reason") or "stop")
        finish_map = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}
        result = {
            "id": response.get("id"),
            "object": "chat.completion",
            "model": response.get("model", model),
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_map.get(finish, finish),
            }],
            "usage": {
                "prompt_tokens": int(usage.get("input_tokens", 0) or 0),
                "completion_tokens": int(usage.get("output_tokens", 0) or 0),
                "total_tokens": int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0),
            },
        }
        return json.dumps(result, ensure_ascii=False)


class OllamaAdapter(OpenAICompatibleAdapter):
    def stream_protocol(self, channel) -> str:
        return "ollama" if (channel.config or {}).get("native_api") else "openai"

    def build_url(self, channel, request) -> str:
        if (channel.config or {}).get("native_api"):
            return _join(channel.base_url, "/api/chat")
        return super().build_url(channel, request)

    def prepare_body(self, channel, request, upstream_model: str) -> dict[str, Any]:
        body = super().prepare_body(channel, request, upstream_model)
        if not (channel.config or {}).get("native_api"):
            return body
        options: dict[str, Any] = dict(body.pop("options", {}) or {})
        if "max_tokens" in body:
            options.setdefault("num_predict", body.pop("max_tokens"))
        for key in ("temperature", "top_p"):
            if key in body:
                options.setdefault(key, body.pop(key))
        if options:
            body["options"] = options
        return body


class GeminiAdapter(ChannelAdapter):
    """Translate OpenAI chat requests to Gemini's native REST contract."""

    def stream_protocol(self, channel) -> str:
        return "gemini"

    def build_url(self, channel, request) -> str:
        configured_path = (channel.config or {}).get("path")
        if configured_path:
            return _join(channel.base_url, str(configured_path))
        base = (channel.base_url or "").rstrip("/")
        model = str(getattr(request, "upstream_model", None) or request.body.get("model") or "")
        # Gateway keeps the selected upstream model outside the public body.
        # DispatchResult is not part of ProxyRequestEntity, so the model is
        # injected by prepare_body and retained in a private request field
        # when available; callers can also configure a path explicitly.
        model = model or str((channel.config or {}).get("model") or "gemini-1.5-flash")
        suffix = "streamGenerateContent?alt=sse" if request.stream else "generateContent"
        return f"{base}/models/{model}:{suffix}"

    def build_headers(self, channel, request) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(request, "upstream_api_key", None) or channel.api_key
        if api_key:
            headers["x-goog-api-key"] = api_key
        headers.update(_copy_headers(channel.config))
        return headers

    @staticmethod
    def _parts(content: Any) -> list[dict[str, str]]:
        if isinstance(content, str):
            return [{"text": content}]
        if isinstance(content, list):
            result = []
            for item in content:
                if isinstance(item, str):
                    result.append({"text": item})
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    result.append({"text": item["text"]})
            return result
        return []

    def prepare_body(self, channel, request, upstream_model: str) -> dict[str, Any]:
        messages = request.body.get("messages") or []
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            parts = self._parts(message.get("content"))
            if not parts:
                continue
            role = str(message.get("role") or "user")
            if role == "system":
                system_parts.extend(parts)
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        source = request.body
        result: dict[str, Any] = {"contents": contents}
        if system_parts:
            result["systemInstruction"] = {"parts": system_parts}
        generation: dict[str, Any] = {}
        for source_key, gemini_key in (("max_tokens", "maxOutputTokens"), ("max_output_tokens", "maxOutputTokens"),
                                       ("temperature", "temperature"), ("top_p", "topP"), ("stop", "stopSequences")):
            if source_key in source and source[source_key] is not None:
                value = source[source_key]
                if source_key == "stop" and isinstance(value, str):
                    value = [value]
                generation[gemini_key] = value
        if generation:
            result["generationConfig"] = generation
        tools = source.get("tools")
        if isinstance(tools, list):
            declarations = []
            for tool in tools:
                function = tool.get("function") if isinstance(tool, dict) else None
                if isinstance(function, dict) and function.get("name"):
                    declarations.append({key: function[key] for key in ("name", "description", "parameters") if key in function})
            if declarations:
                result["tools"] = [{"functionDeclarations": declarations}]
        return result

    def normalize_response(self, body: str, model: str) -> str:
        try:
            response = json.loads(body)
        except (TypeError, ValueError):
            return body
        candidates = response.get("candidates") or []
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        usage = response.get("usageMetadata") or {}
        prompt = int(usage.get("promptTokenCount", 0) or 0)
        completion = int(usage.get("candidatesTokenCount", 0) or 0)
        total = int(usage.get("totalTokenCount", prompt + completion) or prompt + completion)
        finish = str(candidate.get("finishReason") or "STOP").lower()
        result = {"id": response.get("responseId"), "object": "chat.completion", "model": model,
                  "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
                  "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}}
        return json.dumps(result, ensure_ascii=False)


class CustomAdapter(OpenAICompatibleAdapter):
    pass


_ADAPTERS: dict[str, ChannelAdapter] = {
    "claude": AnthropicAdapter(),
    "gemini": GeminiAdapter(),
    "ollama": OllamaAdapter(),
    "custom": CustomAdapter(),
}
_OPENAI_COMPATIBLE = OpenAICompatibleAdapter()


def adapter_for(channel) -> ChannelAdapter:
    """Return the adapter for a channel type, defaulting to OpenAI-compatible."""
    return _ADAPTERS.get(str(channel.type or "openai").lower(), _OPENAI_COMPATIBLE)


def models_url(channel) -> str:
    """Build a provider model-list URL using the channel's API base convention."""
    configured_path = (channel.config or {}).get("models_path")
    if configured_path:
        return _join(channel.base_url, str(configured_path))
    base = (channel.base_url or "").rstrip("/")
    if str(channel.type or "").lower() == "gemini":
        return _join(base, "/models")
    if str(channel.type or "").lower() == "ollama":
        return _join(base.removesuffix("/v1").removesuffix("/api"), "/api/tags")
    return _join(base, "/models" if base.endswith("/v1") else "/v1/models")
