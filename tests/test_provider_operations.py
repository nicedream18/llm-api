"""Account operations exercise real SQL and the public service boundary."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.api.controllers import provider_routes
from app.api.error_handlers import application_error_handler
from app.application.errors import ApplicationError
from app.application.services.provider_service import ProviderService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.provider_repo import ProviderRepository
from app.types.provider import (
    ProviderAccountInput,
    ProviderAccountQuery,
    ProviderBulkInput,
    ProviderOperationInput,
    ProviderTokenInput,
)


@pytest.fixture
def provider_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as db:
        for name in ("014_provider_accounts", "017_provider_resilience", "020_provider_operations", "021_provider_auth_lifecycle", "022_provider_sync"):
            execute_migration(db, Path(f"docs/migrations/{name}.sql"))
        execute_migration(db, Path("docs/migrations/020_provider_operations.sql"))
    service = ProviderService(ProviderRepository(engine))
    yield service
    engine.dispose()


def create(service, name="Primary", provider="codex"):
    return service.create_account(ProviderAccountInput(provider=provider, name=name,
        client_config={"gateway_url": "https://gateway.example"}))


def test_search_filter_sort_and_pagination_are_literal_and_stable(provider_service):
    service = provider_service
    ids = [create(service, name, provider)["id"] for name, provider in (("100%_exact", "codex"), ("Other", "gemini"), ("Other", "codex"))]
    service.operate_account(ids[0], ProviderOperationInput(operation="tags", tags=["a%b_", "a%b_", " 中文 "]))
    service.operate_account(ids[0], ProviderOperationInput(operation="group_name", group_name="Work"))
    result = service.query_accounts(ProviderAccountQuery(search="%_", tag="a%b_", provider="codex", group_name="Work"))
    assert result["total"] == 1 and result["items"][0]["tags"] == ["a%b_", "中文"]
    assert service.query_accounts(ProviderAccountQuery(tag="b_"))["total"] == 0
    page = service.query_accounts(ProviderAccountQuery(sort="name", descending=False, limit=1, offset=1))
    assert page["total"] == 3 and len(page["items"]) == 1
    assert page == service.query_accounts(ProviderAccountQuery(sort="name", descending=False, limit=1, offset=1))
    assert service.query_accounts(ProviderAccountQuery(search="' OR 1=1 --"))["items"] == []
    assert service.query_accounts(ProviderAccountQuery(status="pending", enabled=True))["total"] == 3


def test_bulk_partial_failure_disable_archive_restore_and_audit(provider_service):
    service = provider_service
    account_id = create(service)["id"]
    service.set_token(account_id, ProviderTokenInput(access_token="never-return-this"))
    assert len(service.routing_channels("chat")) == 1
    result = service.bulk_accounts(ProviderBulkInput(account_ids=[account_id, "missing", account_id], operation="enabled", enabled=False))
    assert len(result["results"]) == 2
    assert result["results"][1] == {"id": "missing", "success": False, "error": "not_found"}
    assert service.routing_channels("chat") == []
    assert service.operate_account(account_id, ProviderOperationInput(operation="archive"))["changed"]
    assert not service.operate_account(account_id, ProviderOperationInput(operation="archive"))["changed"]
    assert service.repo.get_token(account_id) is None
    assert service.query_accounts(ProviderAccountQuery())["total"] == 0
    assert service.query_accounts(ProviderAccountQuery(archived=True))["total"] == 1
    with pytest.raises(ApplicationError, match="archived"):
        service.set_token(account_id, ProviderTokenInput(access_token="secret"))
    with pytest.raises(ApplicationError, match="archived"):
        service.operate_account(account_id, ProviderOperationInput(operation="enabled", enabled=True))
    service.operate_account(account_id, ProviderOperationInput(operation="restore"))
    assert not service.operate_account(account_id, ProviderOperationInput(operation="restore"))["changed"]
    assert service.repo.get_token(account_id) is None
    assert service.account_detail(account_id)["enabled"] is False
    events = service.repo.account_events(account_id)
    assert {row["action"] for row in events} == {"token_updated", "enabled", "archive", "restore"}
    assert "never-return-this" not in str(events)
    assert len(service.repo.account_events(account_id, limit=1, offset=1)) == 1


def test_profile_changes_validate_and_account_identity_cannot_change_while_connected(provider_service):
    service = provider_service
    account_id = create(service)["id"]
    with pytest.raises(ApplicationError, match="64"):
        service.operate_account(account_id, ProviderOperationInput(operation="tags", tags=["a" * 65]))
    service.set_token(account_id, ProviderTokenInput(access_token="secret"))
    with pytest.raises(ApplicationError, match="Sign out"):
        service.update_account(account_id, ProviderAccountInput(provider="gemini", name="Changed"))
    with pytest.raises(ApplicationError, match="not found"):
        service.update_account("missing", ProviderAccountInput(provider="codex", name="Missing"))
    with pytest.raises(ValueError, match="Invalid"):
        service.repo.update_account(account_id, {"name=1;--": "injection"})
    with pytest.raises(ApplicationError, match="Invalid account operation"):
        service.repo.operate_account(account_id, "unknown")
    assert not service.operate_account(account_id, ProviderOperationInput(operation="enabled", enabled=True))["changed"]
    service.repo.operate_account(account_id, "group_name", "work")
    assert service.account_detail(account_id)["group_name"] == "work"


def test_public_operations_endpoints_and_invalid_inputs(provider_service, monkeypatch):
    service = provider_service
    account_id = create(service)["id"]
    monkeypatch.setattr(provider_routes, "get_container", lambda: SimpleNamespace(provider_service=service))
    app = FastAPI()
    app.include_router(provider_routes.router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    client = TestClient(app)
    assert client.get("/api/v1/providers/accounts?limit=0").status_code == 422
    assert client.get("/api/v1/providers/accounts?sort=unsafe").status_code == 422
    assert client.get("/api/v1/providers/accounts").json()["data"]["total"] == 1
    assert client.get(f"/api/v1/providers/{account_id}").json()["data"]["auth_status"] == "pending"
    assert client.post(f"/api/v1/providers/{account_id}/operations", json={"operation": "tags", "tags": ["prod"]}).status_code == 200
    assert client.get(f"/api/v1/providers/{account_id}/events").json()["data"][0]["action"] == "tags"
    assert client.get("/api/v1/providers/missing/events").status_code == 404
    assert client.post("/api/v1/providers/bulk", json={"operation": "enabled", "account_ids": [account_id]}).json()["data"]["results"][0]["success"]
    assert client.get("/api/v1/providers").json()["data"][0]["id"] == account_id


def test_operations_transaction_rolls_back_when_audit_fails(provider_service, monkeypatch):
    service = provider_service
    account_id = create(service)["id"]
    service.set_token(account_id, ProviderTokenInput(access_token="secret"))

    def fail(*_args):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service.repo, "_event", fail)
    with pytest.raises(RuntimeError):
        service.repo.operate_account(account_id, "archive")
    assert service.repo.get_token(account_id) is not None
    assert service.repo.get_account(account_id)["status"] == "active"
    with service.repo.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM provider_account_profiles")).scalar() == 1
