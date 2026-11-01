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
