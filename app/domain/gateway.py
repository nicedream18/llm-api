"""Gateway service: dispatches to channels, forwards requests (sync + streaming)."""
import logging
import time
from typing import Callable, Optional

from app.domain.entities import ProxyRequestEntity, ProxyResponseEntity

logger = logging.getLogger(__name__)

# Shared HTTP client
import httpx as _httpx_mod
_http_client = _httpx_mod.Client(
    timeout=_httpx_mod.Timeout(connect=30.0, read=300.0, write=30.0, pool=10.0),
    limits=_httpx_mod.Limits(max_connections=100, max_keepalive_connections=20),
)


def _build_url(channel, request: ProxyRequestEntity) -> str:
    """Build upstream URL based on channel type."""
    base = (channel.base_url or "").rstrip("/")
    ctype = channel.type
    if ctype == "claude":
        return f"{base}/v1/messages"
    elif ctype == "custom":
        path = "/chat/completions"
        if channel.config and channel.config.get("path"):
            path = channel.config["path"]
        return f"{base}{path}"
    else:
        return f"{base}/chat/completions"


def _build_headers(channel, request: ProxyRequestEntity) -> dict:
    """Build auth headers based on channel type."""
    headers = {"Content-Type": "application/json"}
    ctype = channel.type
    if ctype == "claude":
        headers["x-api-key"] = channel.api_key or ""
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {channel.api_key or ''}"
    if ctype == "custom" and channel.config:
        custom_headers = channel.config.get("headers")
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)
    return headers


def _extract_tokens(response_body: str):
    try:
        import json
        j = json.loads(response_body)
        usage = j.get("usage")
        if usage:
            return (
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("total_tokens", 0),
            )
    except Exception:
        pass
    return 0, 0, 0


class GatewayService:
    """Proxy service that dispatches requests to upstream channels."""

    def __init__(self, dispatcher, channel_repository):
        self.dispatcher = dispatcher
        self.channel_repository = channel_repository

    def forward(self, request: ProxyRequestEntity) -> ProxyResponseEntity:
        start = time.time()
        import json

        dispatch_result = self.dispatcher.dispatch(request.model)
        channel = dispatch_result.channel
        request.model = dispatch_result.upstream_model

        url = _build_url(channel, request)
        body_str = json.dumps(request.body)
        headers = _build_headers(channel, request)

        try:
            resp = _http_client.post(url, content=body_str, headers=headers)
            resp_body = resp.text
            pt, ct, tt = _extract_tokens(resp_body)

            return ProxyResponseEntity(
                status_code=resp.status_code,
                body=resp_body,
                success=resp.is_success,
                error_message=None if resp.is_success else resp_body,
                prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
                duration_ms=int((time.time() - start) * 1000),
                channel_id=channel.id, channel_name=channel.name,
                upstream_model=dispatch_result.upstream_model,
            )
        except Exception as e:
            logger.error(f"Forward error for channel={channel.name}: {e}")
            return ProxyResponseEntity(
                success=False, error_message=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

    def forward_stream(self, request: ProxyRequestEntity,
                       on_chunk: Callable[[str], None],
                       on_error: Callable[[Exception], None],
                       on_complete: Callable[[], None]):
        import json

        try:
            dispatch_result = self.dispatcher.dispatch(request.model)
            channel = dispatch_result.channel
            request.model = dispatch_result.upstream_model

            url = _build_url(channel, request)
            body_dict = dict(request.body)
            body_dict["stream"] = True
            headers = _build_headers(channel, request)

            with _http_client.stream("POST", url, json=body_dict, headers=headers) as resp:
                if not resp.is_success:
                    on_error(Exception(f"HTTP {resp.status_code}"))
                    return
                for line in resp.iter_lines():
                    if line and line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            on_chunk(data)
                        except Exception as e:
                            logger.warning(f"Stream onChunk error: {e}")
                            return
            on_complete()
        except Exception as e:
            logger.error(f"Stream forward error: {e}")
            on_error(e)

    def test_channel(self, channel) -> bool:
        try:
            test_request = ProxyRequestEntity(
                model="gpt-3.5-turbo",
                body={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                stream=False,
            )
            url = _build_url(channel, test_request)
            headers = _build_headers(channel, test_request)
            resp = _http_client.post(url, json=test_request.body, headers=headers)
            return resp.is_success
        except Exception:
            return False
