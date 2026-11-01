"""Shared isolated provider database; never uses the application's configured DB."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.application.services.provider_service import ProviderService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.provider_repo import ProviderRepository
from app.types.provider import ProviderAccountInput, ProviderTokenInput


@pytest.fixture
def provider_database(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "providers.db"), connect_args={"check_same_thread": False})
    with engine.begin() as db:
        for path in sorted(Path("docs/migrations").glob("*.sql")):
            if path.name.startswith(("014_", "017_", "020_", "021_", "022_")):
                execute_migration(db, path)
    service = ProviderService(ProviderRepository(engine))
    account = service.create_account(ProviderAccountInput(provider="codex", name="Test account", client_config={
        "quota_url": "https://provider.example/quota", "models_url": "https://provider.example/models",
        "gateway_url": "https://provider.example/v1", "token_url": "https://provider.example/token",
    }))
    service.set_token(account["id"], ProviderTokenInput(access_token="synthetic-access", refresh_token="synthetic-refresh"))
    yield service, account["id"]
    engine.dispose()
