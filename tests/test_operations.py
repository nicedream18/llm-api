"""Analytics correctness, timezone boundaries, budgets and durable alert episodes."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from app.api.controllers import operations_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.application.services.operations_service import (
    OperationsService,
    OperationsWorker,
)
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.alert_repo import AlertRepository
from app.infrastructure.repositories.analytics_repo import AnalyticsRepository
from app.infrastructure.repositories.usage_repo import UsageRepository
from app.types.analytics import AlertRule, AnalyticsQuery
from app.types.usage import PriceInput, UsageFact


@pytest.fixture
def operations(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "operations.db"), connect_args={"check_same_thread": False, "timeout": 10})
    with engine.begin() as db:
        for name in ("024_usage_ledger.sql", "025_operations_alerts.sql"):
            execute_migration(db, Path("docs/migrations") / name)
    usage, analytics, alerts = UsageRepository(engine), AnalyticsRepository(engine), AlertRepository(engine)
    yield usage, analytics, alerts, OperationsService(analytics, alerts)
    engine.dispose()


def event(usage, execution, kind="attempt", **values):
    row = {"execution_id": execution, "event_key": kind, "request_id": "trace-" + execution, "kind": kind, "provider": "openai", "account_id": "account", "model": "demo", "api_key_id": "key", "route_group": "team", "endpoint": "/v1/chat/completions", "outcome": "succeeded", "occurred_at": datetime.now(UTC).isoformat(), "duration_ms": 50}
    if kind == "attempt":
        row.update(input_tokens=3, output_tokens=7, total_tokens=10, usage_source="reported", first_token_ms=5)
    usage.append(UsageFact.model_validate({**row, **values}))


def test_analytics_separates_attempts_final_outcomes_and_currency_costs(operations):
    usage, analytics, _alerts, _service = operations
    for provider, currency in (("openai", "USD"), ("gemini", "EUR")):
        usage.add_price(PriceInput(provider=provider, model="demo", currency=currency, input_per_million="0.125", output_per_million="0.375", effective_at="2020-01-01T00:00:00Z"))
    for index in range(4):
        event(usage, str(index), provider="openai" if index < 2 else "gemini")
        event(usage, str(index), "outcome", provider="openai" if index < 2 else "gemini", status_code=503 if index == 3 else 200, duration_ms=(index + 1) * 100)
    items = analytics.report(AnalyticsQuery())["items"]
    assert len(items) == 1
    item = items[0]
    assert item["requests"] == 4 and item["attempts"] == 4 and item["total_tokens"] == 40
    assert item["costs"] == {"USD": "0.000006", "EUR": "0.000006"}
    assert item["failure_rate"] == 0.25 and item["latency_p50"] == 200 and item["latency_p95"] == 400 and item["latency_p99"] == 400
    assert item["first_token_p95"] == 5
    for name, value in (("provider", "openai"), ("account_id", "account"), ("model", "demo"), ("api_key_id", "key"), ("route_group", "team"), ("endpoint", "/v1/chat/completions")):
        assert analytics.report(AnalyticsQuery(group_by=name, **{name: value}))["items"]
    events = analytics.events(AnalyticsQuery(provider="openai"), limit=2, offset=1)
    assert events["total"] == 4 and len(events["items"]) == 2


def test_timezone_buckets_half_open_ranges_and_unknown_values(operations):
    usage, analytics, _alerts, _service = operations
    event(usage, "a", occurred_at="2026-10-31T15:59:59+00:00", provider=None, usage_source="unknown", input_tokens=None, output_tokens=None, total_tokens=None)
    event(usage, "b", occurred_at="2026-10-31T16:00:00+00:00", usage_source="estimated")
    query = AnalyticsQuery(start="2026-10-31T00:00:00Z", end="2026-11-01T00:00:00Z", timezone="Asia/Shanghai")
    rows = analytics.report(query)["items"]
    assert [row["group"] for row in rows] == ["2026-10-31", "2026-11-01"]
    assert rows[0]["unknown_usage"] == 1 and rows[1]["estimated_usage"] == 1
    assert rows[0]["costs"] == {} and rows[0]["latency_p95"] is None and rows[0]["failure_rate"] is None
    assert analytics.events(query.model_copy(update={"bucket": "2026-11-01"}))["total"] == 1
    hours = analytics.report(query.model_copy(update={"group_by": "hour"}))["items"]
    assert hours[1]["group"] == "2026-11-01T00:00+0800"
    assert analytics.events(query.model_copy(update={"group_by": "hour", "bucket": hours[1]["group"]}))["total"] == 1
    assert analytics.events(query.model_copy(update={"provider": "(unknown)"}))["total"] == 1
    assert analytics.events(query.model_copy(update={"end": datetime.fromisoformat("2026-10-31T16:00:00+00:00")}))["total"] == 1


def test_daylight_saving_hour_buckets_keep_offset_to_avoid_merging_repeated_hour(operations):
    usage, analytics, _alerts, _service = operations
    event(usage, "first", occurred_at="2026-11-01T05:30:00+00:00")
    event(usage, "second", occurred_at="2026-11-01T06:30:00+00:00")
    query = AnalyticsQuery(start="2026-11-01T00:00:00Z", end="2026-11-02T00:00:00Z", timezone="America/New_York", group_by="hour")
    assert {row["group"] for row in analytics.report(query)["items"]} == {"2026-11-01T01:00-0400", "2026-11-01T01:00-0500"}


@pytest.mark.parametrize("values", [{"timezone": "unknown"}, {"start": "2026-01-01"}, {"start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"}, {"start": "2027-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}, {"bucket": "bad"}, {"bucket": "2026-01-01", "group_by": "provider"}, {"group_by": "sql-injection"}])
def test_analytics_rejects_invalid_ranges_and_dimensions(values):
    with pytest.raises(ValidationError):
        AnalyticsQuery.model_validate(values)


def test_analytics_budget_is_explicit_instead_of_silent_truncation(operations, monkeypatch):
    usage, analytics, _alerts, _service = operations
    event(usage, "a", provider="openai")
    event(usage, "b", provider="gemini")
    monkeypatch.setattr(analytics, "MAX_ROWS", 1)
    with pytest.raises(ApplicationError, match="event limit"):
        analytics.report(AnalyticsQuery())
    monkeypatch.setattr(analytics, "MAX_ROWS", 100)
    monkeypatch.setattr(analytics, "MAX_GROUPS", 1)
    with pytest.raises(ApplicationError, match="group limit"):
        analytics.report(AnalyticsQuery(group_by="provider"))


def test_alerts_deduplicate_concurrent_evaluation_acknowledge_resolve_and_recur(operations):
    _usage, _analytics, alerts, _service = operations
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: alerts.transition("rule:scope", True, message="failure"), range(8)))
    assert len(set(ids)) == 1 and len(alerts.list()) == 1
    assert alerts.acknowledge(ids[0], "admin")
    assert not alerts.acknowledge(ids[0], "admin")
    alerts.transition("rule:scope", True)
    assert alerts.list()[0]["status"] == "acknowledged"
    alerts.transition("rule:scope", False)
    assert alerts.list()[0]["status"] == "resolved"
    assert alerts.transition("rule:scope", True) != ids[0]
    assert len(alerts.list()) == 2
    with alerts.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM alert_events")).scalar_one() == 4
    with pytest.raises(ApplicationError, match="not found"):
        alerts.acknowledge("missing", "admin")


@pytest.mark.parametrize("metric,threshold", [("failure_rate", 0.1), ("latency_p95", 10), ("unknown_price", 1)])
def test_alert_evaluation_persists_rules_and_disabled_rules_resolve_existing_episodes(operations, metric, threshold):
    usage, _analytics, alerts, service = operations
    event(usage, "one")
    event(usage, "one", "outcome", status_code=503)
    policy = AlertRule(metric=metric, threshold=threshold, min_samples=1).model_dump()
    alerts.save_rule("rule", policy)
    service.evaluate()
    service.evaluate()
    assert len(alerts.list()) == 1 and alerts.list()[0]["status"] == "open"
    alerts.save_rule("rule", {**policy, "enabled": False})
    service.evaluate()
    assert alerts.list()[0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_operations_worker_survives_database_failure_and_stops(operations, monkeypatch):
    service = operations[-1]
    calls = []

    def unavailable():
        calls.append(1)
        raise RuntimeError("private details")

    monkeypatch.setattr(service, "evaluate", unavailable)
    worker = OperationsWorker(service)
    await worker.start()
    task = worker.task
    await worker.start()
    assert worker.task is task
    await asyncio.sleep(0.05)
    await worker.stop()
    assert calls and worker.task is None


def test_operations_api_validation_filtering_and_acknowledgement(operations, monkeypatch):
    usage, analytics, alerts, service = operations
    event(usage, "one")
    monkeypatch.setattr(operations_routes, "get_container", lambda: SimpleNamespace(analytics_repo=analytics, alert_repo=alerts, operations_service=service))
    app = FastAPI()
    app.include_router(operations_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    assert client.get("/api/v1/operations/analytics?timezone=invalid").status_code == 422
    assert client.get("/api/v1/operations/analytics?group_by=provider").json()["data"]["items"][0]["group"] == "openai"
    assert client.get("/api/v1/operations/events").json()["data"]["total"] == 1
    assert client.post("/api/v1/operations/events/query?limit=1", json={}).json()["data"]["total"] == 1
    assert client.put("/api/v1/operations/alerts/rules/price", json={"metric": "unknown_price", "threshold": 1, "min_samples": 1}).status_code == 200
    assert client.get("/api/v1/operations/alerts/rules").json()["data"]
    assert client.post("/api/v1/operations/alerts/evaluate").status_code == 200
    alert_id = client.get("/api/v1/operations/alerts").json()["data"][0]["id"]
    assert client.post(f"/api/v1/operations/alerts/{alert_id}/acknowledge").json()["data"]["changed"]
