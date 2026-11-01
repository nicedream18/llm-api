"""Async gateway with candidate routing, bounded retries and stream-safe forwarding."""
from __future__ import annotations

import asyncio
import email.utils
import hashlib
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import config
from app.domain.entities import ProxyRequestEntity, ProxyResponseEntity
from app.domain.routing import RoutingPlanner, supports_endpoint
from app.domain.streaming import StreamCodec
from app.domain.usage import estimate_usage, usage_counts
from app.infrastructure.adapters.channel_adapters import adapter_for, models_url

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
    upstream_model: str | None = None
    provider: str | None = None
    account_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    usage_source: str = "unknown"
    first_token_ms: int | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _build_url(channel, request: ProxyRequestEntity) -> str:
    return adapter_for(channel).build_url(channel, request)


def _build_headers(channel, request: ProxyRequestEntity) -> dict:
    return adapter_for(channel).build_headers(channel, request)


def _extract_tokens(response_body: str) -> tuple[int, int, int]:
    if isinstance(response_body, bytes):
        return 0, 0, 0
    usage = usage_counts(response_body) or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), int(usage.get("total_tokens") or 0)


def _response_headers(response: httpx.Response) -> dict[str, str]:
    """Keep only headers safe and useful for a downstream binary response."""
    allowed = {"content-type", "content-disposition", "cache-control", "content-length", "etag", "last-modified"}
    return {key: value for key, value in response.headers.items() if key.lower() in allowed}


class GatewayService:
    def __init__(self, dispatcher, channel_repository, routing_repository=None):
        self.dispatcher = dispatcher
        self.channel_repository = channel_repository
        self.routing = RoutingPlanner(routing_repository, dispatcher) if routing_repository is not None else None
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.gateway.request_timeout_seconds, connect=30.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        self._cooldown_until: dict[str, float] = {}
        self._key_cooldown_until: dict[str, float] = {}

    async def aclose(self):
        await self.client.aclose()

    @staticmethod
    def _retryable_status(status: int) -> bool:
        return status in {408, 425, 429, 500, 502, 503, 504}

    @staticmethod
    def _retry_after_seconds(value: str | None, *, now: float | None = None, maximum: float = 60) -> float:
        """Parse a Retry-After delta or HTTP date and clamp it to a safe bound."""
        if not value:
            return 0.0
        delay = 0.0
        try:
            delay = max(0.0, float(value.strip()))
        except (AttributeError, TypeError, ValueError):
            try:
                target = email.utils.parsedate_to_datetime(value)
                delay = max(0.0, target.timestamp() - (time.time() if now is None else now))
            except (TypeError, ValueError, OverflowError):
                delay = 0.0
        return min(delay, max(0.0, float(maximum)))

    @staticmethod
    def _channel_key(channel) -> str:
        return str(channel.id or channel.name)

    def _select_api_key(self, channel):
        keys = [key for key in getattr(channel, "api_keys", []) if getattr(key, "status", 1) and getattr(key, "api_key", None)]
        if not keys:
            return None, None
        active = [key for key in keys if self._key_cooldown_until.get(self._api_key_id(key), 0.0) <= time.monotonic()]
        if self.routing:
            now = datetime.now(UTC).isoformat()
            active = [key for key in active if (self.routing.repo.state("key:" + self._api_key_id(key)).get("cooldown_until") or "") <= now]
        if not active:
            return "", "__all_keys_cooled__"
        selected = random.choices(active, weights=[max(1, int(getattr(key, "weight", 1) or 1)) for key in active], k=1)[0]
        return selected.api_key, self._api_key_id(selected)

    @staticmethod
    def _api_key_id(key):
        return str(key.id) if key.id else hashlib.sha256(key.api_key.encode()).hexdigest()

    def _has_available_api_key(self, channel) -> bool:
        keys = [key for key in getattr(channel, "api_keys", []) if getattr(key, "status", 1) and getattr(key, "api_key", None)]
        return not keys or any(self._key_cooldown_until.get(self._api_key_id(key), 0.0) <= time.monotonic() for key in keys)

    def _provider_outcome(self, channel, success: bool) -> None:
        account_id = (getattr(channel, "config", None) or {}).get("provider_account_id")
        provider = getattr(self.dispatcher, "provider_source", None)
        if not account_id or provider is None:
            return
        try:
            (provider.record_success if success else provider.record_failure)(account_id)
        except Exception:
            logger.warning("Failed to update provider account health", exc_info=True)

    def _cooldown_key(self, key_id: str | None, retry_after: str | None = None) -> None:
        if not key_id:
            return
        duration = max(float(config.gateway.channel_cooldown_seconds), self._retry_after_seconds(retry_after, maximum=config.gateway.retry_after_max_seconds))
        if duration > 0:
            self._key_cooldown_until[key_id] = time.monotonic() + duration

    @staticmethod
    def _has_key_failover(channel) -> bool:
        return sum(1 for key in getattr(channel, "api_keys", []) if getattr(key, "status", 1) and getattr(key, "api_key", None)) > 1

    def _is_cooled(self, channel) -> bool:
        key = self._channel_key(channel)
        until = self._cooldown_until.get(key, 0.0)
        if until <= time.monotonic():
            self._cooldown_until.pop(key, None)
            return False
        return True

    def _cooldown(self, channel, extra_seconds: float = 0.0) -> None:
        duration = max(float(config.gateway.channel_cooldown_seconds), extra_seconds)
        if duration > 0:
            self._cooldown_until[self._channel_key(channel)] = time.monotonic() + duration

    def _retry_delay(self, attempt_no: int, retry_after: str | None = None) -> float:
        base = config.gateway.retry_backoff_ms / 1000 * (2 ** max(0, attempt_no - 1))
        hint = self._retry_after_seconds(retry_after, maximum=config.gateway.retry_after_max_seconds)
        return max(base, hint)

    async def _backoff(self, attempt_no: int) -> None:
        delay = self._retry_delay(attempt_no)
        if delay > 0:
            await asyncio.sleep(delay + random.uniform(0, delay * 0.2))

    async def _backoff_with_hint(self, attempt_no: int, retry_after: str | None) -> None:
        delay = self._retry_delay(attempt_no, retry_after)
        if delay > 0:
            await asyncio.sleep(delay + random.uniform(0, delay * 0.2))

    def _candidates(self, model: str, excluded: set[str], allowed_channels=frozenset()):
        if hasattr(self.dispatcher, "candidates"):
            return [item for item in self.dispatcher.candidates(model, excluded)
                    if not self._is_cooled(item.channel)
                    if self._has_available_api_key(item.channel)
                    if not allowed_channels or item.channel.id in allowed_channels or item.channel.name in allowed_channels]
        result = self.dispatcher.dispatch(model)
        return [result]

    async def _retry_budget(self, request):
        policy = await asyncio.to_thread(self.routing.policy, request) if self.routing else None
        return min(config.gateway.retry_times, policy.retry_budget) if policy and request.route_group else config.gateway.retry_times

    async def _next_candidate(self, request, excluded):
        if self.routing:
            candidates, policy, _ = await asyncio.to_thread(self.routing.plan, request, excluded)
        else:
            candidates = self._candidates(request.model, excluded, request.allowed_channels)
            policy = None
        for item in candidates:
            if not supports_endpoint(item.channel, request.endpoint) or self._is_cooled(item.channel) or not self._has_available_api_key(item.channel):
                continue
            lease = None
            if self.routing:
                upstream_api_key, key_id = await asyncio.to_thread(self._select_api_key, item.channel)
                if key_id == "__all_keys_cooled__":
                    continue
                lease = await asyncio.to_thread(self.routing.repo.acquire, self._channel_key(item.channel), policy.max_concurrent)
                if not lease:
                    continue
                lease["upstream_api_key"], lease["key_id"] = upstream_api_key, key_id
                if key_id:
                    lease["key_lease"] = await asyncio.to_thread(self.routing.repo.acquire, "key:" + key_id, policy.max_concurrent)
                    if not lease["key_lease"]:
                        await asyncio.to_thread(self.routing.repo.finish, lease)
                        continue
                lease["multi_key"] = self._has_key_failover(item.channel)
                lease["heartbeat"] = asyncio.create_task(self._renew_route(lease, asyncio.current_task()))
            return item, lease
        return None, None

    async def _renew_route(self, lease, parent):
        try:
            while True:
                await asyncio.sleep(20)
                if not await asyncio.to_thread(self.routing.repo.renew, lease):
                    parent.cancel()
                    return
                if lease.get("key_lease") and not await asyncio.to_thread(self.routing.repo.renew, lease["key_lease"]):
                    parent.cancel()
                    return
        except Exception:  # noqa: BLE001 - fail closed if distributed capacity cannot be renewed
            parent.cancel()

    async def _release_route(self, lease, attempt, retry_after=None):
        if not lease:
            return
        lease["heartbeat"].cancel()
        await asyncio.gather(lease["heartbeat"], return_exceptions=True)
        failure = bool(attempt.error_type and (not attempt.status_code or attempt.status_code in {401, 403, 408, 425, 429} or attempt.status_code >= 500))
        try:
            hint = self._retry_after_seconds(retry_after, maximum=config.gateway.retry_after_max_seconds)
            if lease.get("key_lease"):
                await asyncio.to_thread(self.routing.repo.finish, lease["key_lease"], attempt.succeeded, failure, hint)
            await asyncio.to_thread(self.routing.repo.finish, lease, attempt.succeeded, failure and not lease.get("multi_key"), hint)
        except Exception:  # noqa: BLE001 - leases expire when persistence is unavailable
            logger.warning("Failed to release route capacity")

    @staticmethod
    def _attempt(number, channel, model):
        settings = channel.config or {}
        return GatewayAttempt(number, channel.id, channel.name, upstream_model=model,
                              provider=settings.get("provider", channel.type), account_id=settings.get("provider_account_id"))

    @staticmethod
    def _attempt_usage(attempt, usage, estimated=None):
        counts = usage or estimated
        if counts:
            attempt.input_tokens, attempt.output_tokens, attempt.total_tokens = (counts.get(key) for key in ("input_tokens", "output_tokens", "total_tokens"))
            attempt.usage_source = "reported" if usage else "estimated"

    async def forward_with_attempts(self, request: ProxyRequestEntity, on_attempt: Callable[[GatewayAttempt], None] | None = None) -> tuple[ProxyResponseEntity, list[GatewayAttempt]]:
        attempts: list[GatewayAttempt] = []
        excluded: set[str] = set()
        last_response: ProxyResponseEntity | None = None
        budget = await self._retry_budget(request)
        for attempt_no in range(budget + 1):
            dispatch_result, lease = await self._next_candidate(request, excluded)
            if dispatch_result is None:
                break
            channel = dispatch_result.channel
            excluded.add(channel.id or channel.name)
            upstream_model = dispatch_result.upstream_model
            upstream_api_key, key_id = (lease["upstream_api_key"], lease["key_id"]) if lease else self._select_api_key(channel)
            attempt_request = request.__class__(**{**request.__dict__, "upstream_api_key": upstream_api_key,
                                                  "upstream_model": upstream_model})
            started = time.monotonic()
            item = self._attempt(attempt_no + 1, channel, upstream_model)
            retry_after = None
            try:
                body = adapter_for(channel).prepare_body(channel, attempt_request, upstream_model)
                raw_body = adapter_for(channel).prepare_raw_body(channel, attempt_request, upstream_model)
                request_headers = _build_headers(channel, attempt_request)
                if raw_body is not None:
                    request_headers["Content-Type"] = attempt_request.content_type or "application/octet-stream"
                request_kwargs = {"content": raw_body, "headers": request_headers} if raw_body is not None else {"json": body, "headers": request_headers}
                response = await self.client.post(_build_url(channel, attempt_request), **request_kwargs)
                item.status_code = response.status_code
                item.duration_ms = int((time.monotonic() - started) * 1000)
                item.succeeded = response.is_success
                retry_after = response.headers.get("retry-after")
                if response.is_success:
                    self._cooldown_until.pop(self._channel_key(channel), None)
                if response.is_success or response.status_code in {401, 403, 408, 425, 429} or response.status_code >= 500:
                    self._provider_outcome(channel, response.is_success)
                if not response.is_success:
                    item.error_type = "upstream_http"
                    item.error_message = f"upstream returned HTTP {response.status_code}"
                    if self._retryable_status(response.status_code):
                        if not self._has_key_failover(channel):
                            self._cooldown(channel, self._retry_after_seconds(response.headers.get("retry-after"), maximum=config.gateway.retry_after_max_seconds))
                        self._cooldown_key(key_id, retry_after)
                        if self._has_key_failover(channel):
                            excluded.discard(channel.id or channel.name)
                content_type = response.headers.get("content-type")
                is_text = (content_type or "").lower().startswith(("application/json", "text/"))
                response_body = response.text if is_text else ""
                if response_body:
                    response_body = adapter_for(channel).normalize_response(response_body, request.model)
                raw_body = None if is_text else response.content
                pt, ct, tt = _extract_tokens(response_body)
                self._attempt_usage(item, usage_counts(response_body), estimate_usage(request.body, response_body) if response.is_success and is_text else None)
                last_response = ProxyResponseEntity(
                    status_code=response.status_code, body=response_body, raw_body=raw_body,
                    content_type=content_type, success=response.is_success,
                    error_message=None if response.is_success else f"upstream returned HTTP {response.status_code}",
                    prompt_tokens=pt, completion_tokens=ct, total_tokens=tt,
                    duration_ms=item.duration_ms, channel_id=channel.id, channel_name=channel.name,
                    upstream_model=upstream_model,
                    response_headers=_response_headers(response),
                )
                attempts.append(item)
                if on_attempt:
                    await asyncio.to_thread(on_attempt, item)
                if self.channel_repository and hasattr(self.channel_repository, "update_test_result"):
                    self.channel_repository.update_test_result(channel.id, response.is_success)
                if response.is_success or not self._retryable_status(response.status_code):
                    if response.is_success and key_id:
                        self._key_cooldown_until.pop(key_id, None)
                    return last_response, attempts
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                item.error_type = type(exc).__name__
                item.error_message = "upstream connection failed"
                item.duration_ms = int((time.monotonic() - started) * 1000)
                item.succeeded = False
                self._provider_outcome(channel, False)
                attempts.append(item)
                if on_attempt:
                    await asyncio.to_thread(on_attempt, item)
                if self.channel_repository and hasattr(self.channel_repository, "update_test_result"):
                    self.channel_repository.update_test_result(channel.id, False)
                if not self._has_key_failover(channel):
                    self._cooldown(channel)
                self._cooldown_key(key_id)
                if self._has_key_failover(channel):
                    excluded.discard(channel.id or channel.name)
                last_response = ProxyResponseEntity(success=False, status_code=502, error_message="upstream connection failed", duration_ms=item.duration_ms, channel_id=channel.id, channel_name=channel.name, upstream_model=upstream_model)
            finally:
                await self._release_route(lease, item, retry_after)
            if attempt_no < budget:
                await self._backoff_with_hint(attempt_no + 1, retry_after)
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
        budget = await self._retry_budget(request)
        for attempt_no in range(budget + 1):
            dispatch_result, lease = await self._next_candidate(request, excluded)
            if dispatch_result is None:
                break
            channel = dispatch_result.channel
            excluded.add(channel.id or channel.name)
            upstream_api_key, key_id = (lease["upstream_api_key"], lease["key_id"]) if lease else self._select_api_key(channel)
            attempt_request = request.__class__(**{**request.__dict__, "upstream_api_key": upstream_api_key,
                                                  "upstream_model": dispatch_result.upstream_model})
            stream_started = False
            started = time.monotonic()
            attempt = self._attempt(attempt_no + 1, channel, dispatch_result.upstream_model)
            retry_after = None
            codec = None
            output_size = 0
            recorded = False

            async def record_attempt(current_codec, current_output_size, current_attempt=attempt, attempt_started=started) -> None:
                nonlocal recorded
                if recorded:
                    return
                recorded = True
                current_attempt.duration_ms = int((time.monotonic() - attempt_started) * 1000)
                usage = usage_counts({"usage": current_codec.usage}) if current_codec and current_codec.usage else None
                self._attempt_usage(current_attempt, usage, estimate_usage(request.body, current_output_size) if current_output_size else None)
                if on_attempt:
                    await asyncio.to_thread(on_attempt, current_attempt)

            try:
                adapter = adapter_for(channel)
                source_protocol = adapter.stream_protocol(channel)
                body = adapter.prepare_body(channel, attempt_request, dispatch_result.upstream_model)
                raw_body = adapter.prepare_raw_body(channel, attempt_request, dispatch_result.upstream_model)
                request_headers = _build_headers(channel, attempt_request)
                if raw_body is not None:
                    request_headers["Content-Type"] = attempt_request.content_type or "application/octet-stream"
                if source_protocol != "gemini":
                    body["stream"] = True
                codec = StreamCodec(source_protocol, request.protocol_type, request.model)
                request_kwargs = {"content": raw_body, "headers": request_headers} if raw_body is not None else {"json": body, "headers": request_headers}
                async with self.client.stream(
                    "POST", _build_url(channel, attempt_request), **request_kwargs,
                    timeout=httpx.Timeout(config.gateway.stream_timeout_seconds),
                ) as response:
                    if not response.is_success:
                        status = response.status_code
                        attempt.status_code = status
                        attempt.error_type = "upstream_http"
                        attempt.error_message = f"upstream returned HTTP {status}"
                        retry_after = response.headers.get("retry-after")
                        error_body = await response.aread()
                        self._attempt_usage(attempt, usage_counts(error_body.decode("utf-8", "replace")))
                        if status in {401, 403, 408, 425, 429} or status >= 500:
                            self._provider_outcome(channel, False)
                        if self._retryable_status(status) and attempt_no < budget:
                            if not self._has_key_failover(channel):
                                self._cooldown(channel, self._retry_after_seconds(retry_after, maximum=config.gateway.retry_after_max_seconds))
                            self._cooldown_key(key_id, retry_after)
                            if self._has_key_failover(channel):
                                excluded.discard(channel.id or channel.name)
                            await record_attempt(codec, output_size)
                            await self._backoff_with_hint(attempt_no + 1, retry_after)
                            continue
                        await record_attempt(codec, output_size)
                        raise RuntimeError(f"upstream returned HTTP {status}")
                    attempt.status_code = response.status_code
                    async for line in response.aiter_lines():
                        stream_started = True
                        for output in codec.feed_line(line):
                            output_size += len(output)
                            if attempt.first_token_ms is None and any(marker in output for marker in ('"content":', 'output_text.delta', '"text_delta"', '"tool_calls"')):
                                attempt.first_token_ms = int((time.monotonic() - started) * 1000)
                            if codec.done:
                                attempt.succeeded = True
                            for output_line in output.rstrip("\r\n").split("\n"):
                                yield output_line
                            yield ""
                    for output in codec.finish():
                        for output_line in output.rstrip("\r\n").split("\n"):
                            yield output_line
                        yield ""
                    attempt.succeeded = True
                    self._provider_outcome(channel, True)
                    self._cooldown_until.pop(self._channel_key(channel), None)
                    if key_id:
                        self._key_cooldown_until.pop(key_id, None)
                    await record_attempt(codec, output_size)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                last_error = exc
                attempt.error_type = type(exc).__name__
                attempt.error_message = "upstream stream connection failed"
                await record_attempt(codec, output_size)
                if not self._has_key_failover(channel):
                    self._cooldown(channel)
                self._cooldown_key(key_id)
                if self._has_key_failover(channel):
                    excluded.discard(channel.id or channel.name)
                self._provider_outcome(channel, False)
                if stream_started or attempt_no >= budget:
                    raise RuntimeError("upstream stream connection failed") from exc
                await self._backoff(attempt_no + 1)
                continue
            finally:
                try:
                    await record_attempt(codec, output_size)
                finally:
                    await self._release_route(lease, attempt, retry_after)
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

    def sync_models(self, channel) -> list[str]:
        """Fetch and validate a channel's advertised model IDs."""
        async def fetch() -> list[str]:
            response = await self.client.get(models_url(channel), headers=_build_headers(channel, ProxyRequestEntity(model="", body={})))
            if not response.is_success:
                raise RuntimeError(f"model discovery returned HTTP {response.status_code}")
            payload = response.json()
            rows = payload.get("data", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise TypeError("model discovery response is not a list")
            models: list[str] = []
            for row in rows:
                model = row.get("id") if isinstance(row, dict) else row
                if isinstance(model, str) and model.strip() and model.strip() not in models:
                    models.append(model.strip())
            return models

        return asyncio.run(fetch())
