from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.application.services.provider_service import ProviderService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.provider_repo import ProviderRepository
from app.types.provider import ProviderAccountInput, ProviderTokenInput


def test_provider_account_token_is_encrypted_and_oauth_flow_is_mockable(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/014_provider_accounts.sql"))
    repo = ProviderRepository(engine)
    service = ProviderService(repo)
    account = service.create_account(ProviderAccountInput(provider="gemini", name="Gemini", client_config={"authorization_url": "https://accounts.example/authorize", "client_id": "client"}))
    service.set_token(account["id"], ProviderTokenInput(access_token="access-secret", refresh_token="refresh-secret"))
    raw = repo.get_token(account["id"])
    assert raw["access_token"] != "access-secret"
    assert "access-secret" not in str(service.list_accounts())
    auth = service.authorize(account["id"])
    assert auth["state"] and "code_challenge" in auth["authorization_url"]
    connected = service.callback(auth["state"], "authorization-code")
    assert connected["status"] == "active"
    assert {"provider_accounts", "provider_tokens"} <= set(inspect(engine).get_table_names())


def test_provider_rejects_invalid_oauth_state():
    service = ProviderService(type("Repo", (), {})())
    with pytest.raises(Exception, match="state"):
        service.callback("invalid", "code")


def test_configured_provider_uses_http_oauth_and_data_endpoints(monkeypatch):
    from httpx import Response

    from app.domain.provider_adapters import ConfiguredProviderAdapter

    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        if url.endswith("/models"):
            return Response(200, json={"data": [{"id": "model-a"}, {"id": "model-a"}, "model-b"]})
        return Response(200, json={"remaining": 42})

    monkeypatch.setattr("app.domain.provider_adapters.httpx.post", fake_post)
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", fake_get)
    adapter = ConfiguredProviderAdapter("gemini")
    config = {
        "token_url": "https://provider.example/token",
        "quota_url": "https://provider.example/quota",
        "models_url": "https://provider.example/models",
        "client_id": "client",
    }

    token = adapter.exchange_code(config, "code", "verifier")
    refreshed = adapter.refresh(config, "refresh")

    assert token["access_token"] == "access"
    assert refreshed["refresh_token"] == "refresh"
    assert adapter.quota(config, "access")["remaining"] == 42
    assert adapter.models(config, "access") == ["model-a", "model-b"]
    assert calls[0][2]["data"]["code_verifier"] == "verifier"
    assert calls[-1][2]["headers"]["Authorization"] == "Bearer access"


def test_provider_account_delete_removes_encrypted_token(tmp_path):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/014_provider_accounts.sql"))
    repo = ProviderRepository(engine)
    account = repo.create_account({"provider": "codex", "name": "Delete me", "client_config": {}, "model_mapping": {}, "priority": 0})
    repo.save_token(account["id"], {"access_token": "cipher", "refresh_token": None, "expires_at": None})
    assert repo.delete_account(account["id"]) is True
    assert repo.get_account(account["id"]) is None
    assert repo.get_token(account["id"]) is None
    assert repo.delete_account(account["id"]) is False
