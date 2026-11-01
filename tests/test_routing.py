"""Route policy, cross-process capacity, circuit and stream cancellation regressions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.controllers import routing_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.domain.dispatcher import Dispatcher
from app.domain.entities import ChannelApiKeyEntity, ChannelEntity, ProxyRequestEntity
from app.domain.gateway import GatewayService
from app.domain.routing import RoutingPlanner
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.routing_repo import RoutingRepository
from app.types.provider import ProviderTokenInput
from app.types.routing import RoutePolicy


@pytest.fixture
def route_repo(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "routes.db"), connect_args={"check_same_thread": False, "timeout": 10})
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/023_routing.sql"))
        execute_migration(db, Path("docs/migrations/023_routing.sql"))
    yield RoutingRepository(engine)
    engine.dispose()


def dispatcher(*channels, provider=None):
    return Dispatcher(SimpleNamespace(get_enabled_channels=lambda: list(channels)), provider)


def channel(name="one", **kwargs):
    return ChannelEntity(id=name, name=name, base_url=f"https://{name}.example", models=["demo"], **kwargs)


def request(**kwargs):
    return ProxyRequestEntity("demo", {"model": "demo"}, **kwargs)


def test_policy_permissions_endpoint_filters_and_preview_are_read_only(route_repo):
    route_repo.save_policy("team", RoutePolicy(api_key_ids=["key"], channels=["one"], models=["demo"], endpoints=["/v1/embeddings"]).model_dump())
    assert route_repo.groups()[0]["id"] == "team"
    planner = RoutingPlanner(route_repo, dispatcher(channel(), channel("two")))
    with pytest.raises(ApplicationError, match="not found"):
        planner.preview(request(route_group="missing"))
    with pytest.raises(ApplicationError, match="denied"):
        planner.preview(request(route_group="team", principal_id="other", endpoint="/v1/embeddings"))
    value = planner.preview(request(route_group="team", principal_id="key", endpoint="/v1/embeddings"))
    assert value["candidates"] == [{"channel_id": "one", "upstream_model": "demo"}]
    assert next(item for item in value["diagnostics"] if item["channel_id"] == "two")["reason"] == "group_channel_forbidden"
    assert route_repo.state("one")["active"] == 0
    assert "api_key" not in str(value)
    assert not planner.preview(request(allowed_channels=frozenset({"absent"})))["candidates"]
    explicit = RoutingPlanner(route_repo, dispatcher(channel(config={"endpoints": ["/v1/embeddings"]})))
    assert explicit.preview(request())["diagnostics"][0]["reason"] == "endpoint_unsupported"
    legacy = RoutingPlanner(route_repo, dispatcher(channel(type="gemini")))
    assert not legacy.preview(request(endpoint="/v1/embeddings"))["candidates"]


def test_quota_balancing_preserves_priority_and_unknown_is_explicit(route_repo, monkeypatch):
    route_repo.save_policy("balanced", RoutePolicy(strategy="quota_balanced", unknown_quota="deny").model_dump())
    calls = []

    def weighted(values, weights, k):
        calls.append(weights)
        return [values[weights.index(max(weights))]]

    monkeypatch.setattr("app.domain.routing.random.choices", weighted)
    planner = RoutingPlanner(route_repo, dispatcher(channel(config={"quota_status": "normal", "quota_fraction": 0.9}),
        channel("two", config={"quota_status": "low", "quota_fraction": 0.02}), channel("empty", config={"quota_status": "exhausted"}),
        channel("unknown"), channel("high", priority=2, config={"quota_status": "low", "quota_fraction": 0.01})))
    value = planner.preview(request(route_group="balanced"))
    assert [item["channel_id"] for item in value["candidates"]] == ["high", "one", "two"]
    assert calls
    reasons = {item["channel_id"]: item["reason"] for item in value["diagnostics"]}
    assert reasons["empty"] == "quota_exhausted" and reasons["unknown"] == "quota_unknown"


def test_distributed_capacity_claims_are_atomic_and_expired_workers_are_fenced(route_repo):
    other = RoutingRepository(route_repo.engine)
    with ThreadPoolExecutor(max_workers=6) as pool:
        leases = list(pool.map(lambda _: other.acquire("one", 3), range(18)))
    acquired = [value for value in leases if value]
    assert len(acquired) == 3
    assert route_repo.renew(acquired[0])
    assert route_repo.state("one")["active"] == 3
    planner = RoutingPlanner(route_repo, dispatcher(channel()))
    route_repo.save_policy("limited", RoutePolicy(max_concurrent=3).model_dump())
    assert planner.preview(request(route_group="limited"))["diagnostics"][0]["reason"] == "capacity_exhausted"
    for lease in acquired:
        assert route_repo.finish(lease)
        assert not other.finish(lease)
    expired = route_repo.acquire("one", seconds=-1)
    assert not route_repo.renew(expired)
    assert not route_repo.finish(expired, failure=True)
    assert route_repo.acquire("one", 1)


def test_circuit_retry_after_single_probe_and_stale_success_cannot_close(route_repo):
    first, second = route_repo.acquire("one"), route_repo.acquire("one")
    assert route_repo.finish(first, failure=True, retry_after=60)
    assert route_repo.finish(second, success=True)
    assert route_repo.state("one")["failure_count"] == 1
    assert route_repo.acquire("one") is None
    planner = RoutingPlanner(route_repo, dispatcher(channel()))
    assert planner.preview(request())["diagnostics"][0]["reason"] == "cooling"
    with route_repo.engine.begin() as db:
        db.execute(text("UPDATE route_runtime SET cooldown_until='2000-01-01'"))
    probe = route_repo.acquire("one")
    assert probe and route_repo.acquire("one") is None
    assert planner.preview(request())["diagnostics"][0]["reason"] == "capacity_exhausted"
    assert route_repo.finish(probe, success=True)
    state = route_repo.state("one")
    assert state["failure_count"] == 0 and state["success_count"] == 2 and state["error_count"] == 1


@pytest.mark.asyncio
async def test_gateway_limits_are_shared_and_cancellation_releases_capacity(route_repo):
    route_repo.save_policy("limited", RoutePolicy(max_concurrent=1).model_dump())
    first, second = GatewayService(dispatcher(channel()), None, route_repo), GatewayService(dispatcher(channel()), None, RoutingRepository(route_repo.engine))
    entered = asyncio.Event()

    async def slow(_request):
        entered.set()
        await asyncio.Event().wait()

    await first.aclose()
    first.client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    task = asyncio.create_task(first.forward(request(route_group="limited")))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (await second.forward(request(route_group="limited"))).status_code == 503
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert route_repo.state("one")["active"] == 0
        assert route_repo.state("one")["failure_count"] == 0
    finally:
        task.cancel()
        await first.aclose()
        await second.aclose()


@pytest.mark.parametrize("status,failure", [(400, 0), (401, 1), (429, 1), (503, 1), (200, 0)])
@pytest.mark.asyncio
async def test_gateway_classifies_upstream_failures_and_honors_group_budget(route_repo, status, failure):
    route_repo.save_policy("single", RoutePolicy(retry_budget=0).model_dump())
    service = GatewayService(dispatcher(channel()), None, route_repo)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, json={"ok": True})))
    try:
        result, attempts = await service.forward_with_attempts(request(route_group="single"))
        assert result.status_code == status and len(attempts) == 1
        assert route_repo.state("one")["failure_count"] == failure
        assert route_repo.state("one")["active"] == 0
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_stream_close_releases_persistent_lease_without_retry(route_repo):
    service = GatewayService(dispatcher(channel()), None, route_repo)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'data: {"partial":true}\n\n')))
    stream = service.stream(request(stream=True))
    try:
        assert "partial" in await anext(stream)
        assert route_repo.state("one")["active"] == 1
        await stream.aclose()
        assert route_repo.state("one")["active"] == 0
    finally:
        await service.aclose()


def test_provider_cooldown_uses_exact_time_and_snapshots_filter_exhaustion(provider_database, monkeypatch):
    from datetime import UTC, datetime, timedelta

    service, account = provider_database
    repo = service.repo
    assert service.routing_channels("demo")
    service.record_failure(account)
    assert not service.routing_channels("demo")
    assert service.account_detail(account)["health_status"] == "cooling"
    repo.clear_failures(account)
    _, _, generation = repo.read_sync_credentials(account)
    from app.domain.provider_quota import normalize_quota

    repo.save_snapshot(account, "quota", generation, normalize_quota({"unit": "requests", "remaining": 0, "limit": 100}))
    assert not service.routing_channels("demo")
    repo.save_snapshot(account, "quota", generation, normalize_quota({"unit": "requests", "remaining": 50, "limit": 100}))
    assert service.routing_channels("demo")[0].config["quota_fraction"] == 0.5
    service.set_token(account, ProviderTokenInput(access_token="next", refresh_token="refresh", expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()))
    monkeypatch.setattr(service, "refresh", lambda *_: pytest.fail("preview must not refresh credentials"))
    assert service.routing_channels("demo", preview=True) == []


def test_routing_management_api_validation(route_repo, monkeypatch):
    planner = RoutingPlanner(route_repo, dispatcher(channel()))
    monkeypatch.setattr(routing_routes, "get_container", lambda: SimpleNamespace(routing_repo=route_repo, gateway=SimpleNamespace(routing=planner)))
    app = FastAPI()
    app.include_router(routing_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    assert client.put("/api/v1/routing/groups/team", json={"max_concurrent": 1}).status_code == 200
    assert client.get("/api/v1/routing/groups").json()["data"][0]["id"] == "team"
    assert client.post("/api/v1/routing/preview", json={"model": "demo", "route_group": "team"}).json()["data"]["candidates"]
    assert client.put("/api/v1/routing/groups/team", json={"max_concurrent": 0}).status_code == 422
    assert client.post("/api/v1/routing/preview", json={"model": "demo", "route_group": "missing"}).status_code == 404


@pytest.mark.asyncio
async def test_multi_key_failover_and_cooling_survive_gateway_restart(route_repo, monkeypatch):
    keys = [ChannelApiKeyEntity(id="a", api_key="synthetic-a"), ChannelApiKeyEntity(id="b", api_key="synthetic-b")]
    upstream = channel(api_keys=keys)
    service = GatewayService(dispatcher(upstream), None, route_repo)
    calls = []

    async def send(req):
        calls.append(req.headers["authorization"])
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    async def no_backoff(*_):
        return None

    monkeypatch.setattr(service, "_backoff_with_hint", no_backoff)
    await service.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(send))
    try:
        assert (await service.forward(request())).success
        assert len(set(calls)) == 2
        fresh = GatewayService(dispatcher(upstream), None, RoutingRepository(route_repo.engine))
        await fresh.aclose()
        fresh.client = httpx.AsyncClient(transport=httpx.MockTransport(send))
        try:
            assert (await fresh.forward(request())).success
            assert calls[-1] == calls[-2]
        finally:
            await fresh.aclose()
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_capacity_renewal_failure_cancels_inflight_request(route_repo, monkeypatch):
    service = GatewayService(dispatcher(channel()), None, route_repo)
    parent = SimpleNamespace(cancel=lambda: cancellations.append(True))
    cancellations = []

    async def instant(_):
        return None

    monkeypatch.setattr("app.domain.gateway.asyncio.sleep", instant)
    monkeypatch.setattr(route_repo, "renew", lambda *_: False)
    try:
        await service._renew_route({"id": "expired"}, parent)
        assert cancellations == [True]
    finally:
        await service.aclose()
