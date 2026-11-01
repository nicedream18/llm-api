"""Accounting regression: retries, missing prices, Decimal versions and partial streams."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.api.controllers import usage_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.application.services.misc_services import ProxyService
from app.application.services.usage_service import UsageRecorder
from app.domain.dispatcher import Dispatcher
from app.domain.entities import ChannelEntity, ProxyRequestEntity
from app.domain.gateway import GatewayAttempt, GatewayService
from app.domain.usage import usage_counts
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.usage_repo import UsageRepository
from app.types.auth import AuthContext
from app.types.usage import PriceInput, UsageFact


@pytest.fixture
def usage_repo(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "usage.db"), connect_args={"check_same_thread": False, "timeout": 10})
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/024_usage_ledger.sql"))
        execute_migration(db, Path("docs/migrations/024_usage_ledger.sql"))
    yield UsageRepository(engine)
    engine.dispose()


def fact(**values):
    return UsageFact(execution_id="execution", event_key="attempt:1", request_id="trace", kind="attempt", provider="openai", model="demo", endpoint="/v1/chat/completions", outcome="succeeded", occurred_at="2026-11-02T00:00:00+00:00", **values)


def price(**values):
    return PriceInput(provider="openai", model="demo", currency="USD", input_per_million="0.125", output_per_million="0.375", **values)


def test_ledger_is_idempotent_under_concurrent_writes_and_rejects_conflicting_facts(usage_repo):
    value = fact(input_tokens=10, output_tokens=2, total_tokens=12, usage_source="reported")
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: usage_repo.append(value), range(10)))
    assert sum(results) == 1
    with pytest.raises(ApplicationError, match="conflicts"):
        usage_repo.append(value.model_copy(update={"total_tokens": 99}))
    assert len(usage_repo.execution("execution")) == 1
    assert usage_repo.by_request("trace")[0]["pricing_status"] == "missing_price"
    assert usage_repo.by_request("trace")[0]["cost"] is None


def test_decimal_prices_are_versioned_and_old_facts_never_repriced(usage_repo):
    old = usage_repo.add_price(price(effective_at="2026-01-01T00:00:00Z"))
    value = fact(input_tokens=3, output_tokens=7, total_tokens=10, usage_source="reported")
    assert usage_repo.append(value)
    row = usage_repo.execution("execution")[0]
    assert row["cost"] == "0.000003" and row["currency"] == "USD" and row["price_version"] == old["id"]
    new = usage_repo.add_price(price(effective_at="2026-11-01T00:00:00Z").model_copy(update={"input_per_million": Decimal("1.5")}))
    assert not usage_repo.append(value)
    assert usage_repo.execution("execution")[0]["price_version"] == old["id"]
    next_value = value.model_copy(update={"execution_id": "next", "usage_source": "estimated"})
    assert usage_repo.append(next_value)
    assert usage_repo.execution("next")[0]["price_version"] == new["id"]
    assert usage_repo.execution("next")[0]["pricing_status"] == "estimated"
    assert len(usage_repo.prices()) == 2
    usage_repo.append(value.model_copy(update={"execution_id": "unknown", "input_tokens": None}))
    assert usage_repo.execution("unknown")[0]["pricing_status"] == "unknown_usage"
    assert usage_repo.execution("unknown")[0]["cost"] is None


@pytest.mark.parametrize("payload", [{"input_per_million": "NaN"}, {"output_per_million": "-1"}, {"effective_at": "2026-01-01"}, {"currency": "usd"}])
def test_invalid_prices_are_rejected(payload):
    with pytest.raises(ValidationError):
        PriceInput.model_validate({"provider": "openai", "model": "demo", "currency": "USD", "input_per_million": "1", "output_per_million": "1", **payload})


@pytest.mark.parametrize("payload", ['[]', '{"usage":{"total_tokens":"invalid"}}', '{"usage":false}', "not-json", '{"usage":{"input_tokens":true}}'])
def test_malformed_usage_stays_unknown(payload):
    assert usage_counts(payload) is None


def test_usage_distinguishes_total_only_zero_and_missing():
    assert usage_counts({"usage": {"total_tokens": 17}}) == {"input_tokens": None, "output_tokens": None, "total_tokens": 17}
    assert usage_counts({"usage": {"prompt_tokens": 0, "completion_tokens": 0}})["total_tokens"] == 0
    assert usage_counts({"usage": {"input_tokens": 3, "output_tokens": 4}})["total_tokens"] == 7


def proxy(repository, handler, *channels):
    gateway = GatewayService(Dispatcher(SimpleNamespace(get_enabled_channels=lambda: list(channels))), None)
    asyncio.run(gateway.aclose())
    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    logs, quota = [], []
    quota_repo = SimpleNamespace(reserve=lambda *_: "reservation", settle=lambda *args: quota.append(("settle", *args)), release=lambda *args: quota.append(("release", *args)))
    log_repo = SimpleNamespace(insert_log=logs.append, insert_attempt=lambda *_: None)
    service = ProxyService(gateway, None, SimpleNamespace(enabled=False, scan_response=False), log_repo, quota_repository=quota_repo, usage_repository=repository)
    return service, gateway, logs, quota


def test_retry_consumption_is_separate_from_final_outcome_and_client_trace_reuse(usage_repo):
    channels = [ChannelEntity(id="first", name="first", priority=2, base_url="https://first.example"), ChannelEntity(id="second", name="second", base_url="https://second.example")]

    def handler(req):
        return httpx.Response(503 if req.url.host == "first.example" else 200, json={"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})

    service, gateway, logs, quota = proxy(usage_repo, handler, *channels)
    context = AuthContext("api_key", "key", "client")
    try:
        assert service.forward('{"model":"demo"}', {}, auth_context=context, request_id="same-trace")[0] == 200
        assert quota[-1] == ("settle", "reservation", 10)
        rows = usage_repo.by_request("same-trace")
        assert len(rows) == 3
        assert sorted(row["kind"] for row in rows) == ["attempt", "attempt", "outcome"]
        assert next(row for row in rows if row["kind"] == "outcome")["total_tokens"] is None
        assert service.forward('{"model":"demo"}', {}, auth_context=context, request_id="same-trace")[0] == 200
        assert len({row["execution_id"] for row in usage_repo.by_request("same-trace")}) == 2
        assert len(logs) == 2
    finally:
        asyncio.run(gateway.aclose())


@pytest.mark.asyncio
async def test_stream_usage_and_outcome_are_recorded_when_downstream_stops_at_done(usage_repo):
    content = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: {"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}\n\ndata: [DONE]\n\n'
    service, gateway, logs, quota = await asyncio.to_thread(proxy, usage_repo, lambda _: httpx.Response(200, content=content), ChannelEntity(id="one", base_url="https://one.example"))
    try:
        frames = [item async for item in service.forward_stream_async('{"model":"demo"}', {}, auth_context=AuthContext("api_key", "key"), request_id="stream")]
        assert frames[-1] == "data: [DONE]\n\n"
        rows = usage_repo.by_request("stream")
        assert len(rows) == 2 and next(row for row in rows if row["kind"] == "attempt")["total_tokens"] == 7
        assert quota[-1] == ("settle", "reservation", 7)
        assert logs[0].total_tokens == 7
    finally:
        await gateway.aclose()


@pytest.mark.asyncio
async def test_partial_stream_disconnect_preserves_estimated_consumption(usage_repo):
    content = b'data: {"choices":[{"delta":{"content":"partial output"}}]}\n\n'
    service, gateway, _logs, quota = await asyncio.to_thread(proxy, usage_repo, lambda _: httpx.Response(200, content=content), ChannelEntity(id="one", base_url="https://one.example"))
    stream = service.forward_stream_async('{"model":"demo"}', {}, auth_context=AuthContext("api_key", "key"), request_id="partial")
    try:
        assert "partial" in await anext(stream)
        await stream.aclose()
        rows = usage_repo.by_request("partial")
        attempt = next(row for row in rows if row["kind"] == "attempt")
        assert attempt["total_tokens"] > 0 and attempt["usage_source"] == "estimated"
        assert next(row for row in rows if row["kind"] == "outcome")["outcome"] == "client_disconnect"
        assert quota[-1][0] == "settle" and quota[-1][2] > 0
    finally:
        await gateway.aclose()


def test_anthropic_passthrough_still_accumulates_usage():
    from app.domain.streaming import StreamCodec

    codec = StreamCodec("anthropic", "anthropic", "demo")
    for line in ['data: {"type":"message_start","message":{"usage":{"input_tokens":3,"output_tokens":0}}}', "", 'data: {"type":"message_delta","usage":{"output_tokens":5}}', ""]:
        codec.feed_line(line)
    assert codec.usage == {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}


def test_recorder_repeated_callback_and_finalization_do_not_double_charge(usage_repo):
    recorder = UsageRecorder(usage_repo, "run", "trace", ProxyRequestEntity("demo", {}))
    item = GatewayAttempt(1, "one", "one", input_tokens=3, output_tokens=2, total_tokens=5, usage_source="reported")
    recorder.attempt(item)
    recorder.attempt(item)
    recorder.finish("completed", 200, 10)
    recorder.finish("completed", 200, 10)
    assert recorder.consumed == 5 and len(usage_repo.execution("run")) == 2


def test_price_and_drilldown_api(usage_repo, monkeypatch):
    monkeypatch.setattr(usage_routes, "get_container", lambda: SimpleNamespace(usage_repo=usage_repo))
    app = FastAPI()
    app.include_router(usage_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    assert client.post("/api/v1/usage/prices", json=price().model_dump(mode="json")).status_code == 201
    assert len(client.get("/api/v1/usage/prices").json()["data"]) == 1
    assert client.get("/api/v1/usage/requests/missing").json()["data"] == []
