"""OAuth persistence, identity binding and delayed credential writes."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.controllers import provider_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.application.services.provider_service import ProviderService
from app.domain.provider_adapters import ConfiguredProviderAdapter, require_endpoint
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.provider_repo import ProviderRepository
from app.types.provider import (
    ProviderAccountInput,
    ProviderOperationInput,
    ProviderTokenInput,
)

CONFIG = {"authorization_url": "https://provider.example/authorize?scope=chat&state=untrusted", "token_url": "https://provider.example/token", "client_id": "public", "redirect_uri": "http://localhost/callback"}


@pytest.fixture
def connected(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "provider.db"), connect_args={"check_same_thread": False})
    with engine.begin() as db:
        for name in ("014_provider_accounts", "017_provider_resilience", "020_provider_operations", "021_provider_auth_lifecycle", "022_provider_sync"):
            execute_migration(db, Path(f"docs/migrations/{name}.sql"))
        execute_migration(db, Path("docs/migrations/021_provider_auth_lifecycle.sql"))
    service = ProviderService(ProviderRepository(engine))
    account = service.create_account(ProviderAccountInput(provider="codex", name="Work", client_config=CONFIG))
    service.set_token(account["id"], ProviderTokenInput(access_token="original-secret", refresh_token="original-refresh"))
    monkeypatch.setattr("app.domain.provider_adapters.httpx.post", lambda *_args, **_kwargs: httpx.Response(200, json={"access_token": "rotated-secret", "refresh_token": "rotated-refresh"}))
    yield service, account["id"]
    engine.dispose()


def test_oauth_survives_service_restart_binds_subject_and_consumes_once(connected):
    service, account = connected
    authorization = service.authorize(account, ("admin", "alice"))
    assert authorization["authorization_url"].count("state=") == 1
    assert "scope=chat" in authorization["authorization_url"]
    with service.repo.engine.connect() as db:
        record = db.execute(text("SELECT * FROM provider_oauth_states")).mappings().one()
        assert authorization["state"] not in str(record)
        assert service._decrypt(record["verifier"]) != record["verifier"]
    restarted = ProviderService(ProviderRepository(service.repo.engine))
    with pytest.raises(ApplicationError, match="does not belong"):
        restarted.callback(authorization["state"], "code", ("admin", "bob"), "codex")
    with pytest.raises(ApplicationError, match="does not belong"):
        restarted.callback(authorization["state"], "code", ("admin", "alice"), "gemini")
    assert restarted.callback(authorization["state"], "code", ("admin", "alice"), "codex")["status"] == "active"
    with pytest.raises(ApplicationError, match="state"):
        restarted.callback(authorization["state"], "code", ("admin", "alice"), "codex")
    assert "rotated-secret" not in str(restarted.list_accounts())


@pytest.mark.parametrize("change", ["expire", "configuration", "logout", "denied", "missing_code"])
def test_oauth_rejects_expiry_configuration_changes_logout_and_denial(connected, change):
    service, account = connected
    authorization = service.authorize(account)
    if change == "expire":
        with service.repo.engine.begin() as db:
            db.execute(text("UPDATE provider_oauth_states SET expires_at='2000-01-01'"))
    elif change == "configuration":
        service.repo.update_account(account, {"client_config": {**CONFIG, "client_id": "changed"}})
    elif change == "logout":
        service.sign_out(account)
    with pytest.raises(ApplicationError):
        service.callback(authorization["state"], "" if change == "missing_code" else "code", error="denied" if change == "denied" else None)
    with service.repo.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM provider_oauth_states")).scalar() == 0


@pytest.mark.parametrize("change", ["logout", "archive", "manual_token"])
def test_delayed_refresh_cannot_overwrite_new_authorization_state(connected, monkeypatch, change):
    service, account = connected
    entered, finish = Event(), Event()

    def delayed(*_args, **_kwargs):
        entered.set()
        assert finish.wait(5)
        return httpx.Response(200, json={"access_token": "stale-refreshed-secret"})

    monkeypatch.setattr("app.domain.provider_adapters.httpx.post", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.refresh, account)
        assert entered.wait(5)
        with pytest.raises(ApplicationError) as busy:
            ProviderService(ProviderRepository(service.repo.engine)).refresh(account)
        assert busy.value.code == "refresh_in_progress"
        if change == "logout":
            service.repo.delete_token(account)
        elif change == "archive":
            service.operate_account(account, ProviderOperationInput(operation="archive"))
        else:
            service.set_token(account, ProviderTokenInput(access_token="new-manual-secret"))
        finish.set()
        with pytest.raises(ApplicationError):
            future.result(timeout=5)
    token = service.repo.get_token(account)
    assert token is None if change != "manual_token" else service._decrypt(token["access_token"]) == "new-manual-secret"


def test_refresh_lease_expiry_release_ownership_and_missing_tokens(connected):
    service, account = connected
    token = service.repo.claim_refresh(account, "old", lease_seconds=-1)
    current = service.repo.claim_refresh(account, "new")
    service.repo.release_refresh(account, "old")
    with pytest.raises(ApplicationError) as error:
        service.repo.store_token(account, {key: token[key] for key in ("access_token", "refresh_token", "expires_at")}, token["generation"], "old")
    assert error.value.code == "refresh_lease_expired"
    service.repo.release_refresh(account, "new")
    assert current["generation"] == token["generation"]
    service.sign_out(account)
    with pytest.raises(ApplicationError, match="not connected"):
        service.refresh(account)


def test_refresh_validation_and_revoke_failure_never_restore_token(connected, monkeypatch, caplog):
    service, account = connected
    monkeypatch.setattr("app.domain.provider_adapters.httpx.post", lambda *_args, **_kwargs: httpx.Response(401, text="original-secret"))
    with pytest.raises(ApplicationError) as error:
        service.refresh(account)
    assert error.value.code == "provider_reauthorization_required"
    assert "original-secret" not in str(error.value)
    service.repo.update_account(account, {"client_config": {**CONFIG, "revoke_url": "https://provider.example/revoke"}})
    assert service.sign_out(account)
    assert service.repo.get_token(account) is None
    assert "original-secret" not in caplog.text


def test_browser_callback_and_capability_matrix(connected, monkeypatch):
    service, account = connected
    monkeypatch.setattr(provider_routes, "get_container", lambda: SimpleNamespace(provider_service=service))
    app = FastAPI()
    app.include_router(provider_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    authorization = client.post(f"/api/v1/providers/{account}/authorize").json()["data"]
    assert client.get("/api/v1/providers/callback/codex", params={"state": authorization["state"], "code": "one-use-code"}).status_code == 200
    assert client.get("/api/v1/providers/capabilities").json()["data"][0]["vendor_verified"] is False
    assert client.get("/api/v1/providers/callback/codex?state=short").status_code == 422


@pytest.mark.parametrize("method", ["exchange_code", "refresh", "quota", "models", "revoke"])
def test_unconfigured_adapter_never_fakes_success(method):
    adapter = ConfiguredProviderAdapter("codex")
    with pytest.raises(ApplicationError):
        getattr(adapter, method)({}, "code", "verifier") if method == "exchange_code" else getattr(adapter, method)({}, "token")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://u:p@example.com/token", "https://example.com/token#fragment", "https://", "https://[bad", "https://example.com:bad"])
def test_provider_endpoint_validation(url):
    with pytest.raises(ApplicationError):
        require_endpoint(url)


def test_state_is_invalidated_after_manual_token_change(connected):
    service, account = connected
    authorization = service.authorize(account)
    service.set_token(account, ProviderTokenInput(access_token="manual"))
    with pytest.raises(ApplicationError):
        service.callback(authorization["state"], "code")
    with service.repo.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM provider_oauth_states WHERE state_hash=:hash"), {"hash": hashlib.sha256(authorization["state"].encode()).hexdigest()}).scalar() == 0


def test_authorization_configuration_and_archived_accounts_are_rejected(connected):
    service, account = connected
    service.operate_account(account, ProviderOperationInput(operation="archive"))
    with pytest.raises(ApplicationError, match="archived"):
        service.authorize(account)
    with pytest.raises(ApplicationError, match="archived"):
        service.repo.claim_refresh(account, "owner")
    for settings in ({}, {"authorization_url": "https://provider.example/auth"}):
        with pytest.raises(ApplicationError) as error:
            ConfiguredProviderAdapter("codex").authorize_url(settings, "state", "challenge")
        assert error.value.code == "provider_not_configured"
    with pytest.raises(ApplicationError, match="not found"):
        service.sign_out("missing")
    with pytest.raises(ValueError, match="expiry"):
        ProviderTokenInput(access_token="x", expires_at="not-a-date")
    assert ProviderTokenInput(access_token="x", expires_at="2000000000").expires_at.endswith("+00:00")


def test_config_change_between_authorization_read_and_store_is_rejected(connected):
    service, account = connected
    authorization = service.authorize(account)
    with service.repo.engine.connect() as db:
        record = dict(db.execute(text("SELECT * FROM provider_oauth_states")).mappings().one())
    service.repo.update_account(account, {"client_config": {**CONFIG, "client_id": "different"}})
    with pytest.raises(ApplicationError, match="configuration changed"):
        service.repo.store_oauth(record)
    assert authorization["state"]
