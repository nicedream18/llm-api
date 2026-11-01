from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.application.errors import ApplicationError
from app.application.services.access_service import AccessService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.access_repo import AccessRepository
from app.types.access import AccessGrantInput
from app.types.auth import AuthContext


@pytest.fixture
def access():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/010_access_grants.sql"))
    yield AccessService(AccessRepository(engine))
    engine.dispose()


def grant(
    access,
    principal_id="key-1",
    resource_type="wiki",
    resource_id="project-1",
    action="read",
):
    return access.repo.create(
        AccessGrantInput(
            principal_type="api_key",
            principal_id=principal_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
        ).model_dump()
    )


def test_default_deny_and_explicit_scopes(access):
    context = AuthContext("api_key", "key-1")
    assert not access.can(context, "wiki", "project-1")
    assert not access.can(None, "wiki", "project-1")
    assert access.can(AuthContext("admin", "admin"), "wiki", "any")
    row = grant(access)
    assert access.can(context, "wiki", "project-1")
    assert not access.can(context, "wiki", "project-2")
    assert not access.can(context, "wiki", "project-1", "write")
    assert not access.can(AuthContext("mcp", "key-1"), "wiki", "project-1")
    assert not access.can(AuthContext("api_key", "key-2"), "wiki", "project-1")
    access.repo.delete(row["id"])
    with pytest.raises(ApplicationError) as error:
        access.require(context, "wiki", "project-1")
    assert error.value.status_code == 403


def test_wildcards_are_explicit_and_duplicates_are_rejected(access):
    row = grant(access, resource_id="*")
    assert access.can(AuthContext("api_key", "key-1"), "wiki", "any")
    with pytest.raises(ApplicationError) as error:
        grant(access, resource_id="*")
    assert error.value.status_code == 409
    assert access.repo.list_grants() == [row]


def test_mcp_tools_and_kb_permissions_are_both_required(access):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from app.application.services.misc_services import McpService

    kb = Mock()
    kb.list_kbs.return_value = [
        SimpleNamespace(id="kb-1", name="Visible", description="", index_status="none"),
        SimpleNamespace(id="kb-2", name="Private", description="", index_status="none"),
    ]
    kb.search_kb.return_value = []
    service = McpService(kb, access)
    context = AuthContext("api_key", "key-1")
    assert service.list_tools(context)["tools"] == []
    grant(
        access,
        resource_type="mcp_tool",
        resource_id="list_knowledge_bases",
        action="execute",
    )
    grant(
        access,
        resource_type="mcp_tool",
        resource_id="search_knowledge_base",
        action="execute",
    )
    grant(access, resource_type="kb", resource_id="kb-1")
    assert len(service.list_tools(context)["tools"]) == 2
    listed = service.call_tool("list_knowledge_bases", {}, context)
    assert [row["id"] for row in listed["knowledgeBases"]] == ["kb-1"]
    denied = service.call_tool(
        "search_knowledge_base", {"kb_id": "kb-2", "query": "q"}, context
    )
    assert denied["isError"] is True
    kb.search_kb.assert_not_called()
    allowed = service.call_tool(
        "search_knowledge_base", {"kb_id": "kb-1", "query": "q"}, context
    )
    assert allowed["resultCount"] == 0
    kb.search_kb.assert_called_once()


def test_kb_http_reads_require_resource_grants(access, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.controllers.routes import kb_router
    from app.api.error_handlers import application_error_handler
    from app.api.middleware.auth import ApiKeyAuthMiddleware
    from app.types.models import KbKnowledgeBaseDTO

    kb = Mock()
    kb.list_kbs.return_value = [
        KbKnowledgeBaseDTO(id="kb-1"),
        KbKnowledgeBaseDTO(id="kb-2"),
    ]
    kb.get_kb.return_value = KbKnowledgeBaseDTO(id="kb-1")
    container = SimpleNamespace(
        kb_service=kb, access_service=access, channel_repo=Mock()
    )
    for module in (
        "app.api.controllers.routes",
        "app.api.resource_dependencies",
        "app.api.middleware.auth",
    ):
        monkeypatch.setattr(f"{module}.get_container", lambda: container)
    authorizer = Mock()
    authorizer.authenticate.return_value = AuthContext("api_key", "key-1")
    monkeypatch.setattr(
        "app.api.middleware.auth.ApiKeyAuthorizer", lambda repo: authorizer
    )
    app = FastAPI()
    app.include_router(kb_router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_middleware(ApiKeyAuthMiddleware)
    client = TestClient(app, headers={"Authorization": "Bearer readonly"})
    assert client.get("/api/v1/kb").json()["data"] == []
    assert client.get("/api/v1/kb/kb-1").status_code == 403
    grant(access, resource_type="kb", resource_id="kb-1")
    listed = client.get("/api/v1/kb").json()["data"]
    assert [row["id"] for row in listed] == ["kb-1"]
    assert client.get("/api/v1/kb/kb-1").status_code == 200
    assert client.get("/api/v1/kb/kb-2/documents").status_code == 403
    kb.list_docs.assert_not_called()
