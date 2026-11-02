"""Synchronization semantics, quota units, lease fencing and recovery."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.controllers import provider_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.application.services.provider_sync_worker import ProviderSyncWorker
from app.domain.provider_quota import normalize_quota, quota_status
from app.types.provider import ProviderTokenInput
from app.types.provider_sync import ProviderSyncSettings


@pytest.mark.parametrize("minutes", [0, 16, 360, 720])
@pytest.mark.parametrize("models", [["known-model"], []])
def test_model_snapshot_age_never_turns_known_set_into_wildcard(provider_database, minutes, models):
    service, account = provider_database
    repo = service.repo
    _, _, generation = repo.read_sync_credentials(account)
    assert repo.save_snapshot(account, "models", generation, {"models": models})
    with repo.engine.begin() as db:
        db.execute(text("UPDATE provider_snapshots SET fetched_at=:when WHERE account_id=:id AND kind='models'"),
                   {"id": account, "when": (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()})
    assert service._discovered_models(account) == models
    assert service.routing_channels("unlisted-model") == []
    assert bool(service.routing_channels("known-model")) is bool(models)
    # Explicit mappings remain an intentional administrator routing choice.
    repo.update_account(account, {"model_mapping": {"explicit": "upstream"}})
    assert service.routing_channels("explicit")[0].model_mapping == {"explicit": "upstream"}
    assert service.routing_channels("unlisted-model") == []


@pytest.mark.parametrize("remaining,limit,unit,status", [(1, 100, "tokens", "low"), (30, 100, "requests", "normal"), (0, 100, "credits", "exhausted"), (0, 100, "unknown", "unknown"), (1, 100, "currency", "unknown")])
def test_quota_window_states(remaining, limit, unit, status):
    value = normalize_quota({"remaining": remaining, "limit": limit, "unit": unit})
    assert value["status"] == status
    assert value["source"] == "reported"


def test_quota_windows_are_not_combined_and_old_reset_is_stale():
    value = normalize_quota({"windows": [{"unit": "tokens", "remaining": 500}, {"unit": "currency", "currency": "USD", "remaining": "1.125"}]})
    assert len(value["windows"]) == 2 and "total" not in value
    assert value["windows"][1]["remaining"] == "1.125"
    assert quota_status({**value, "fetched_at": (datetime.now(UTC) - timedelta(minutes=16)).isoformat()}) == "stale"
    value["windows"][0]["reset_at"] = "2000-01-01"
    assert quota_status(value) == "stale"
    value["windows"][0]["reset_at"] = "invalid"
    assert quota_status(value) == "unknown"
    assert normalize_quota({})["status"] == "unknown"


@pytest.mark.parametrize("payload", [[], {"windows": "invalid"}, {"windows": [None]}, {"remaining": "NaN"}, {"remaining": 0, "limit": 0}])
def test_malformed_quota_does_not_become_unlimited(payload):
    with pytest.raises(ApplicationError, match="Invalid quota"):
        normalize_quota(payload)


def test_synchronization_persists_safe_snapshots_and_preserves_last_good_value(provider_database, monkeypatch):
    service, account = provider_database
    responses = [httpx.Response(200, json={"unit": "requests", "remaining": 42, "access_token": "synthetic-access"}), httpx.Response(503, text="synthetic-access")]
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: responses.pop(0))
    assert service.quota(account)["remaining"] == 42
    state = service.sync_state(account)
    assert state["snapshots"]["quota"]["payload"]["status"] == "normal"
    assert "synthetic-access" not in str(state)
    with pytest.raises(ApplicationError):
        service.quota(account)
    failed = service.sync_state(account)["snapshots"]["quota"]
    assert failed["payload"]["windows"][0]["remaining"] == "42" and failed["error_code"] == "provider_error"
    service.set_token(account, ProviderTokenInput(access_token="new-token"))
    assert service.sync_state(account)["snapshots"]["quota"]["payload"]["status"] == "stale"
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(503))
    with pytest.raises(ApplicationError):
        service.quota(account)
    assert service.sync_state(account)["snapshots"]["quota"]["payload"]["status"] == "stale"


@pytest.mark.parametrize("payload", [{}, {"models": "invalid"}, None])
def test_malformed_models_preserve_last_good_snapshot(provider_database, monkeypatch, payload):
    service, account = provider_database
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(200, json={"models": ["good"]}))
    assert service.models(account) == {"models": ["good"]}
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(200, content=json.dumps(payload)))
    with pytest.raises(ApplicationError):
        service.models(account)
    assert service.sync_state(account)["snapshots"]["models"]["payload"] == {"models": ["good"]}


def test_manual_jobs_are_idempotent_and_sync_models(provider_database, monkeypatch):
    service, account = provider_database
    repo = service.repo
    first = repo.enqueue_sync(account, "models")
    assert repo.enqueue_sync(account, "models")["id"] == first["id"]
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(200, json={"data": [{"id": "chat"}, {"id": "synthetic-access"}]}))
    worker = ProviderSyncWorker(service, repo)
    job = repo.claim_sync(worker.owner)
    assert repo.claim_sync("other") is None
    worker.execute(job)
    state = service.sync_state(account)
    assert state["jobs"][0]["status"] == "succeeded"
    assert state["snapshots"]["models"]["payload"] == {"models": ["chat"]}
    assert repo.enqueue_sync(account, "models")["id"] == first["id"]


def test_expired_job_cannot_overwrite_newer_work_and_lease_recovery_is_bounded(provider_database):
    service, account = provider_database
    repo = service.repo
    repo.enqueue_sync(account, "quota")
    old = repo.claim_sync("old", lease_seconds=-1)
    current = repo.claim_sync("new")
    _, _, generation = repo.read_sync_credentials(account)
    with pytest.raises(ApplicationError, match="lease expired"):
        repo.save_snapshot(account, "quota", generation, normalize_quota({}), job=old)
    assert not repo.finish_sync(old)
    assert repo.finish_sync(current)
    repo.enqueue_sync(account, "quota")
    for _ in range(3):
        assert repo.claim_sync("crashed", lease_seconds=-1)
    assert repo.claim_sync("last") is None
    assert service.sync_state(account)["jobs"][0]["status"] == "failed"


def test_retry_and_stale_snapshot_fencing(provider_database, monkeypatch):
    service, account = provider_database
    repo = service.repo
    repo.enqueue_sync(account, "quota")
    worker = ProviderSyncWorker(service, repo)
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(429))
    job = repo.claim_sync(worker.owner)
    worker.execute(job)
    assert service.sync_state(account)["jobs"][0]["status"] == "pending"
    assert repo.claim_sync("another") is None
    _, _, generation = repo.read_sync_credentials(account)
    assert repo.save_snapshot(account, "quota", generation, normalize_quota({"unit": "tokens", "remaining": 2}))
    assert not repo.save_snapshot(account, "quota", generation, normalize_quota({"unit": "tokens", "remaining": 0}), requested_at="2000-01-01")
    service.repo.delete_token(account)
    with pytest.raises(ApplicationError, match="authorization changed"):
        repo.save_snapshot(account, "quota", generation, {})
    with pytest.raises(ApplicationError, match="not connected"):
        repo.enqueue_sync(account, "quota")
    with pytest.raises(ApplicationError, match="not connected"):
        repo.read_sync_credentials(account)


def test_auto_sync_requires_opt_in_and_honors_intervals(provider_database):
    service, account = provider_database
    repo = service.repo
    repo.schedule_sync()
    assert service.sync_state(account)["jobs"] == []
    repo.configure_sync(account, ProviderSyncSettings(enabled=True).model_dump())
    repo.schedule_sync()
    assert len(service.sync_state(account)["jobs"]) == 2
    repo.schedule_sync()
    assert len(service.sync_state(account)["jobs"]) == 2
    repo.configure_sync(account, ProviderSyncSettings(enabled=False).model_dump())
    assert not service.sync_state(account)["settings"]["enabled"]


def test_sync_api_and_input_validation(provider_database, monkeypatch):
    service, account = provider_database
    monkeypatch.setattr(provider_routes, "get_container", lambda: SimpleNamespace(provider_service=service, provider_repo=service.repo))
    app = FastAPI()
    app.include_router(provider_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    assert client.get(f"/api/v1/providers/{account}/sync").json()["data"]["settings"]["enabled"] is False
    assert client.post(f"/api/v1/providers/{account}/sync", json={}).status_code == 202
    assert client.post(f"/api/v1/providers/{account}/sync", json={"kinds": ["unsafe"]}).status_code == 422
    assert client.put(f"/api/v1/providers/{account}/sync/settings", json={"enabled": True}).status_code == 200
    assert client.put(f"/api/v1/providers/{account}/sync/settings", json={"quota_interval": 0}).status_code == 422


@pytest.mark.asyncio
async def test_worker_start_stop_and_database_failure_are_recoverable(provider_database, monkeypatch):
    service, _account = provider_database
    worker = ProviderSyncWorker(service, service.repo, count=1)
    calls = []

    def unavailable():
        calls.append("attempt")
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(service.repo, "schedule_sync", unavailable)
    await worker.start()
    await worker.start()
    await asyncio.sleep(0.05)
    assert worker.running and calls
    await worker.stop()
    assert not worker.running


@pytest.mark.asyncio
async def test_worker_runs_queued_work_and_survives_idle_poll(provider_database, monkeypatch):
    service, account = provider_database
    repo = service.repo
    repo.enqueue_sync(account, "models")
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", lambda *_args, **_kwargs: httpx.Response(200, json={"models": ["chat"]}))
    worker = ProviderSyncWorker(service, repo, count=1)
    await worker.start()
    for _ in range(40):
        await asyncio.sleep(0.01)
        if service.sync_state(account)["jobs"][0]["status"] == "succeeded":
            break
    assert service.sync_state(account)["jobs"][0]["status"] == "succeeded"
    await asyncio.sleep(1.05)
    await worker.stop()
    assert not worker.running


def test_worker_generic_failure_and_max_retries(provider_database, monkeypatch):
    service, account = provider_database
    repo = service.repo
    repo.enqueue_sync(account, "quota")
    worker = ProviderSyncWorker(service, repo)
    job = repo.claim_sync(worker.owner)

    def fail(*_args):
        raise RuntimeError("private upstream details")

    monkeypatch.setattr(service, "_provider_data", fail)
    worker.execute(job)
    assert service.sync_state(account)["jobs"][0]["error_code"] == "sync_failed"
    with repo.engine.begin() as db:
        db.execute(text("UPDATE provider_sync_jobs SET attempts=2,available_at='2000-01-01'"))
    job = repo.claim_sync(worker.owner)
    worker.execute(job)
    assert service.sync_state(account)["jobs"][0]["status"] == "failed"
