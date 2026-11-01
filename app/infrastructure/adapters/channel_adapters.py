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
        elif getattr(request, "protocol_type", "") in {"responses", "anthropic"}:
            # Non-OpenAI public requests are converted before the compatible
            # upstream call, so use the Chat Completions endpoint.
            path = "/chat/completions"
        else:
            path = _endpoint_path(request)
        return _join(channel.base_url, str(path))

    def build_headers(self, channel, request) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if channel.api_key:
            headers["Authorization"] = f"Bearer {channel.api_key}"
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
        if channel.api_key:
            headers["x-api-key"] = channel.api_key
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
            anthropic_messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})

        body: dict[str, Any] = {
            "model": upstream_model,
            "messages": anthropic_messages,
            "max_tokens": source.pop("max_tokens", source.pop("max_output_tokens", 4096)),
        }
        if system:
            body["system"] = "\n\n".join(str(item) for item in system)
        for key in ("temperature", "top_p", "stop_sequences", "stream", "tools", "tool_choice"):
            if key in source:
                body[key] = source[key]
        return body

    def normalize_response(self, body: str, model: str) -> str:
        """Convert a non-streaming Anthropic message into Chat Completions."""
        try:
            response = json.loads(body)
        except (TypeError, ValueError):
            return body
        content = response.get("content") or []
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
        usage = response.get("usage") or {}
        result = {
            "id": response.get("id"),
            "object": "chat.completion",
            "model": response.get("model", model),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": response.get("stop_reason") or "stop",
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


class CustomAdapter(OpenAICompatibleAdapter):
    pass


_ADAPTERS: dict[str, ChannelAdapter] = {
    "claude": AnthropicAdapter(),
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
    return _join(base, "/models" if base.endswith("/v1") else "/v1/models")
