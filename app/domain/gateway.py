"""Async gateway with candidate routing, bounded retries and stream-safe forwarding."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx

from app.config import config
from app.domain.entities import ProxyRequestEntity, ProxyResponseEntity

logger = logging.getLogger(__name__)


@dataclass
class GatewayAttempt:
    attempt_no: int
    channel_id: str | None
    channel_name: str | None
    status_code: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    succeeded: bool = False


def _build_url(channel, request: ProxyRequestEntity) -> str:
    base = (channel.base_url or "").rstrip("/")
    if channel.type == "claude":
        return f"{base}/v1/messages"
    if channel.type == "ollama" and (channel.config or {}).get("native_api"):
        return f"{base}/api/chat"
    if channel.type == "custom":
        return f"{base}{(channel.config or {}).get('path', '/chat/completions')}"
    return f"{base}/chat/completions"


def _build_headers(channel, request: ProxyRequestEntity) -> dict:
    headers = {"Content-Type": "application/json"}
    if channel.type == "claude":
        headers.update({"x-api-key": channel.api_key or "", "anthropic-version": "2023-06-01"})
    else:
        headers["Authorization"] = f"Bearer {channel.api_key or ''}"
    custom = (channel.config or {}).get("headers")
    if isinstance(custom, dict):
        headers.update({str(k): str(v) for k, v in custom.items()})
    return headers


def _extract_tokens(response_body: str) -> tuple[int, int, int]:
    if isinstance(response_body, bytes):
        return 0, 0, 0
    try:
        usage = json.loads(response_body).get("usage") or {}
        prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        return prompt, completion, int(usage.get("total_tokens", prompt + completion) or prompt + completion)
    except (ValueError, TypeError, json.JSONDecodeError):
        return 0, 0, 0


class GatewayService:
    def __init__(self, dispatcher, channel_repository):
        self.dispatcher = dispatcher
        self.channel_repository = channel_repository
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.gateway.request_timeout_seconds, connect=30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def aclose(self):
        await self.client.aclose()

    @staticmethod
    def _retryable_status(status: int) -> bool:
        return status in {408, 425, 429, 500, 502, 503, 504}

    async def _backoff(self, attempt_no: int) -> None:
        if config.gateway.retry_backoff_ms <= 0:
            return
        delay = config.gateway.retry_backoff_ms / 1000 * (2 ** max(0, attempt_no - 1))
        await asyncio.sleep(delay + random.uniform(0, delay * 0.2))

    def _candidates(self, model: str, excluded: set[str], allowed_channels=frozenset()):
        if hasattr(self.dispatcher, "candidates"):
            return [item for item in self.dispatcher.candidates(model, excluded)
                    if not allowed_channels or item.channel.id in allowed_channels or item.channel.name in allowed_channels]
        result = self.dispatcher.dispatch(model)
        return [result]

    async def forward_with_attempts(self, request: ProxyRequestEntity, on_attempt: Callable[[GatewayAttempt], None] | None = None) -> tuple[ProxyResponseEntity, list[GatewayAttempt]]:
        attempts: list[GatewayAttempt] = []
        excluded: set[str] = set()
        last_response: ProxyResponseEntity | None = None
        for attempt_no in range(config.gateway.retry_times + 1):
            candidates = self._candidates(request.model, excluded, request.allowed_channels)
            if not candidates:
                break
            dispatch_result = candidates[0]
            channel = dispatch_result.channel
            excluded.add(channel.id or channel.name)
            upstream_model = dispatch_result.upstream_model
            body = dict(request.body)
            body["model"] = upstream_model
            started = time.monotonic()
            item = GatewayAttempt(attempt_no + 1, channel.id, channel.name)
            try:
                response = await self.client.post(_build_url(channel, request), json=body, headers=_build_headers(channel, request))
                item.status_code = response.status_code
                item.duration_ms = int((time.monotonic() - started) * 1000)
                item.succeeded = response.is_success
                if not response.is_success:
                    item.error_type = "upstream_http"
                    item.error_message = f"upstream returned HTTP {response.status_code}"
                content_type = response.headers.get("content-type")
                is_text = (content_type or "").lower().startswith(("application/json", "text/"))
                response_body = response.text if is_text else ""
                raw_body = None if is_text else response.content
                pt, ct, tt = _extract_tokens(response_body)
                last_response = ProxyResponseEntity(
                    status_code=response.status_code, body=response_body, raw_body=raw_body,
                    content_type=content_type, success=response.is_success,
                    error_message=None if response.is_success else f"upstream returned HTTP {response.status_code}",
                    prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
                    duration_ms=item.duration_ms, channel_id=channel.id, channel_name=channel.name,
                    upstream_model=upstream_model,
                )
                attempts.append(item)
                if on_attempt:
                    on_attempt(item)
                if self.channel_repository and hasattr(self.channel_repository, "update_test_result"):
                    self.channel_repository.update_test_result(channel.id, response.is_success)
                if response.is_success or not self._retryable_status(response.status_code):
                    return last_response, attempts
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                item.error_type = type(exc).__name__
                item.error_message = "upstream connection failed"
                item.duration_ms = int((time.monotonic() - started) * 1000)
                item.succeeded = False
                attempts.append(item)
                if on_attempt:
                    on_attempt(item)
                if self.channel_repository and hasattr(self.channel_repository, "update_test_result"):
                    self.channel_repository.update_test_result(channel.id, False)
                last_response = ProxyResponseEntity(success=False, status_code=502, error_message="upstream connection failed", duration_ms=item.duration_ms, channel_id=channel.id, channel_name=channel.name, upstream_model=upstream_model)
            if attempt_no < config.gateway.retry_times:
                await self._backoff(attempt_no + 1)
        return last_response or ProxyResponseEntity(success=False, status_code=503, error_message="No available upstream channel"), attempts

    async def forward(self, request: ProxyRequestEntity, on_attempt=None) -> ProxyResponseEntity:
        response, _attempts = await self.forward_with_attempts(request, on_attempt)
        return response

    def forward_sync(self, request: ProxyRequestEntity) -> ProxyResponseEntity:
        """Compatibility bridge for synchronous domain services."""
        return asyncio.run(self.forward(request))

    async def stream(self, request: ProxyRequestEntity, on_attempt: Callable[[GatewayAttempt], None] | None = None) -> AsyncIterator[str]:
        excluded: set[str] = set()
        last_error: Exception | None = None
        for attempt_no in range(config.gateway.retry_times + 1):
            candidates = self._candidates(request.model, excluded, request.allowed_channels)
            if not candidates:
                break
            dispatch_result = candidates[0]
            channel = dispatch_result.channel
            excluded.add(channel.id or channel.name)
            body = dict(request.body)
            body["model"] = dispatch_result.upstream_model
            body["stream"] = True
            stream_started = False
            started = time.monotonic()
            attempt = GatewayAttempt(attempt_no + 1, channel.id, channel.name)

            def record_attempt(current_attempt=attempt, attempt_started=started) -> None:
                current_attempt.duration_ms = int((time.monotonic() - attempt_started) * 1000)
                if on_attempt:
                    try:
                        on_attempt(current_attempt)
                    except Exception:
                        logger.warning("Failed to record streaming gateway attempt", exc_info=True)

            try:
                async with self.client.stream(
                    "POST", _build_url(channel, request), json=body,
                    headers=_build_headers(channel, request),
                    timeout=httpx.Timeout(config.gateway.stream_timeout_seconds),
                ) as response:
                    if not response.is_success:
                        status = response.status_code
                        attempt.status_code = status
                        attempt.error_type = "upstream_http"
                        attempt.error_message = f"upstream returned HTTP {status}"
                        if self._retryable_status(status) and attempt_no < config.gateway.retry_times:
                            await response.aread()
                            record_attempt()
                            await self._backoff(attempt_no + 1)
                            continue
                        record_attempt()
                        raise RuntimeError(f"upstream returned HTTP {status}")
                    attempt.status_code = response.status_code
                    async for line in response.aiter_lines():
                        stream_started = True
                        # Preserve SSE fields and boundaries. Blank lines are meaningful.
                        yield line
                    attempt.succeeded = True
                    record_attempt()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                attempt.error_type = type(exc).__name__
                attempt.error_message = "upstream stream connection failed"
                record_attempt()
                if stream_started or attempt_no >= config.gateway.retry_times:
                    raise RuntimeError("upstream stream connection failed") from exc
                await self._backoff(attempt_no + 1)
                continue
            return
        if last_error:
            raise RuntimeError("upstream stream connection failed") from last_error
        raise RuntimeError("No available upstream channel")

    def test_channel(self, channel) -> bool:
        """Run a minimal non-streaming request against a channel."""
        model = (channel.models or [None])[0] or next(iter((channel.model_mapping or {}).keys()), "gpt-4o-mini")
        body = {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}

        async def send_test() -> bool:
            try:
                response = await self.client.post(
                    _build_url(channel, ProxyRequestEntity(model=model, body=body)),
                    json=body,
                    headers=_build_headers(channel, ProxyRequestEntity(model=model, body=body)),
                )
                return response.is_success
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
                return False

        return asyncio.run(send_test())
