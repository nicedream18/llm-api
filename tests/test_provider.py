import os
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


@pytest.mark.parametrize("provider", ["codex", "gemini", "grok", "kimi", "qoder", "workbuddy"])
def test_all_provider_adapters_share_redacted_http_contract(monkeypatch, provider):
    from httpx import Response

    from app.domain.provider_adapters import adapter_for

    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        if kwargs.get("data", {}).get("grant_type") == "refresh_token":
            return Response(200, json={"access_token": "rotated", "refresh_token": "next", "expires_in": 60})
        return Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 60})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        if url.endswith("/models"):
            return Response(200, json={"data": [{"id": "model-a"}, {"id": "model-a"}]})
        return Response(200, json={"remaining": 42})

    monkeypatch.setattr("app.domain.provider_adapters.httpx.post", fake_post)
    monkeypatch.setattr("app.domain.provider_adapters.httpx.get", fake_get)
    adapter = adapter_for(provider)
    config = {
        "token_url": "https://provider.example/token",
        "models_url": "https://provider.example/models",
        "quota_url": "https://provider.example/quota",
        "revoke_url": "https://provider.example/revoke",
        "client_id": "public-client",
    }
    assert adapter.exchange_code(config, "code", "verifier")["access_token"] == "access"
    assert adapter.refresh(config, "refresh")["access_token"] == "rotated"
    assert adapter.models(config, "access") == ["model-a"]
    assert adapter.quota(config, "access")["remaining"] == 42
    adapter.revoke(config, "access")
    revoke_call = calls[-1]
    assert revoke_call[2]["data"]["token"] == "access"


def test_provider_client_secrets_require_environment_references(monkeypatch):
    service = ProviderService(type("Repo", (), {})())
    with pytest.raises(Exception, match="environment reference"):
        service.create_account(ProviderAccountInput(provider="codex", name="Invalid", client_config={"client_secret": "inline"}))
    monkeypatch.setenv("WALIAPI_PROVIDER_CLIENT_SECRET", "secret")
    assert service._resolve_client_value({"client_secret": {"env": "WALIAPI_PROVIDER_CLIENT_SECRET"}})["client_secret"] == "secret"
    monkeypatch.delenv("WALIAPI_PROVIDER_MISSING", raising=False)
    with pytest.raises(Exception, match="not configured"):
        service._resolve_client_value({"client_secret": {"env": "WALIAPI_PROVIDER_MISSING"}})


@pytest.mark.skipif(
    not (os.environ.get("WALIAPI_PROVIDER_LIVE_URL") and os.environ.get("WALIAPI_PROVIDER_LIVE_TOKEN")),
    reason="Set WALIAPI_PROVIDER_LIVE_URL and WALIAPI_PROVIDER_LIVE_TOKEN for real Provider contract validation",
)
def test_provider_live_contract_is_opt_in():
    """Run only in a controlled environment; credentials never enter test output."""
    from app.domain.provider_adapters import ConfiguredProviderAdapter

    adapter = ConfiguredProviderAdapter("live")
    base_url = os.environ["WALIAPI_PROVIDER_LIVE_URL"].rstrip("/")
    config = {"quota_url": base_url + "/quota", "models_url": base_url + "/models"}
    assert isinstance(adapter.quota(config, os.environ["WALIAPI_PROVIDER_LIVE_TOKEN"]), dict)
    assert isinstance(adapter.models(config, os.environ["WALIAPI_PROVIDER_LIVE_TOKEN"]), list)
