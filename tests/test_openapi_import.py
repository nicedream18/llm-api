from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from app.application.errors import ApplicationError
from app.application.services.software_service import SoftwareService
from app.domain.openapi_tools import parse_openapi_tools
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.software_repo import SoftwareRepository

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Example", "version": "1.0"},
    "servers": [{"url": "https://api.example.test/v1/{region}", "variables": {"region": {"default": "us"}}}],
    "components": {
        "schemas": {
            "SearchBody": {
                "type": "object", "required": ["query"], "additionalProperties": False,
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            },
        },
        "parameters": {
            "ItemId": {"name": "itemId", "in": "path", "required": True, "schema": {"type": "string"}},
        },
    },
    "paths": {
        "/items/{itemId}": {
            "parameters": [{"$ref": "#/components/parameters/ItemId"}],
            "get": {
                "operationId": "getItem", "summary": "Read an item",
                "parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
            },
        },
        "/search": {
            "post": {
                "operationId": "search", "requestBody": {"required": True, "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/SearchBody"}},
                }},
            },
        },
    },
}


def test_openapi_preview_resolves_local_refs_without_network_access():
    preview = parse_openapi_tools(SPEC)
    assert preview["tool_count"] == 2
    read_item, search = preview["tools"]
    assert read_item["name"] == "getItem"
    assert read_item["config"]["server_url"] == "https://api.example.test/v1/us"
    assert read_item["input_schema"]["required"] == ["path__itemId"]
    assert read_item["config"]["bindings"] == [
        {"field": "path__itemId", "in": "path", "name": "itemId", "explode": False},
        {"field": "query__q", "in": "query", "name": "q", "explode": True},
    ]
    assert search["input_schema"]["required"] == ["body"]
    assert search["input_schema"]["properties"]["body"]["required"] == ["query"]
    assert all(tool["approval_mode"] == "per_call" for tool in preview["tools"])


@pytest.mark.parametrize("bad_spec", [
    {"openapi": "2.0", "paths": {"/x": {"get": {}}}},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {"parameters": [{"$ref": "https://example.test/secret"}]}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {"parameters": [{"$ref": "#/components/parameters/missing"}]}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {"parameters": [{"name": "token", "in": "header", "schema": {"type": "string"}}]}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/items/{id}": {"get": {}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {"parameters": [{"name": "q", "in": "query", "style": "spaceDelimited", "schema": {"type": "array", "items": {"type": "string"}}}]}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {"parameters": [{"name": "q", "in": "query", "schema": {"oneOf": [{"type": "string"}]}}]}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/../admin": {"get": {}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"post": {"requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object"}}}}}}}, "servers": [{"url": "https://api.example.test"}]},
    {"openapi": "3.0.0", "paths": {"/x": {"get": {}}}, "servers": [{"url": "https://user:pass@api.example.test"}]},
])
def test_openapi_preview_rejects_unsupported_or_dangerous_specs(bad_spec):
    with pytest.raises(ApplicationError):
        parse_openapi_tools(bad_spec)


def test_openapi_import_is_atomic_and_invocation_maps_path_query_and_json_body(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'software-openapi.sqlite'}")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
    repo = SoftwareRepository(engine)
    service = SoftwareService(repo)
    imported = service.import_openapi("Example API", SPEC, ["getItem", "search"])
    assert imported["instance"]["connector_type"] == "openapi"
    assert {tool["name"] for tool in imported["tools"]} == {"getItem", "search"}

    class Response:
        status_code = 200
        content = b'{"ok":true}'
        text = '{"ok":true}'

        @staticmethod
        def json():
            return {"ok": True}

    calls = []
    monkeypatch.setattr("app.application.services.software_service.ImportGuard.remote_url", lambda url: url)
    monkeypatch.setattr(
        "app.application.services.software_service.httpx.request",
        lambda method, url, **kwargs: calls.append((method, url, kwargs)) or Response(),
    )
    read_tool = next(tool for tool in imported["tools"] if tool["name"] == "getItem")
    search_tool = next(tool for tool in imported["tools"] if tool["name"] == "search")
    assert service.invoke(read_tool["id"], {"path__itemId": "folder/item", "query__q": "hello"}, approved=True) == {"ok": True}
    with pytest.raises(ApplicationError, match="Required tool arguments"):
        service.invoke(search_tool["id"], {"body": {"limit": 5}}, approved=True)
    assert len(calls) == 1
    assert service.invoke(search_tool["id"], {"body": {"query": "hello", "limit": 5}}, approved=True) == {"ok": True}
    assert calls[0][0:2] == ("GET", "https://api.example.test/v1/us/items/folder%2Fitem")
    assert calls[0][2]["params"] == {"q": "hello"}
    assert calls[1][0:2] == ("POST", "https://api.example.test/v1/us/search")
    assert calls[1][2]["json"] == {"query": "hello", "limit": 5}
    assert len(repo.list_calls()) == 3
    engine.dispose()


def test_openapi_import_selection_validation_and_ssrf_guard(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'software-openapi-selection.sqlite'}")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
    service = SoftwareService(SoftwareRepository(engine))
    with pytest.raises(ApplicationError, match="does not exist"):
        service.import_openapi("No tools", SPEC, ["missing"])
    assert service.repo.list_instances() == []

    internal_spec = {
        "openapi": "3.0.0", "servers": [{"url": "http://127.0.0.1/private"}],
        "paths": {"/read": {"get": {"operationId": "read"}}},
    }
    imported = service.import_openapi("Internal", internal_spec)
    with pytest.raises(ApplicationError, match="Private or local"):
        service.invoke(imported["tools"][0]["id"], {}, approved=True)
    assert len(service.repo.list_calls()) == 1
    engine.dispose()


def test_openapi_import_rolls_back_instance_when_tool_insert_fails(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'software-openapi-rollback.sqlite'}")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/013_software_tools.sql"))
    repo = SoftwareRepository(engine)
    preview = parse_openapi_tools(SPEC)["tools"][0]
    with pytest.raises(IntegrityError):
        repo.import_openapi(
            {"name": "Rollback", "connector_type": "openapi", "config": {}, "enabled": True},
            [preview, preview],
        )
    assert repo.list_instances() == []
    assert repo.list_tools() == []
    engine.dispose()


def test_openapi_preview_enforces_document_and_operation_limits():
    oversized = {"openapi": "3.0.0", "info": {"description": "x" * 1_050_000}, "servers": [{"url": "https://api.example.test"}], "paths": {"/x": {"get": {}}}}
    with pytest.raises(ApplicationError, match="size limit"):
        parse_openapi_tools(oversized)
    many = {
        "openapi": "3.0.0", "servers": [{"url": "https://api.example.test"}],
        "paths": {f"/path-{index}": {"get": {}} for index in range(101)},
    }
    with pytest.raises(ApplicationError, match="too many operations"):
        parse_openapi_tools(many)


def test_software_call_summaries_redact_credentials_and_bearer_tokens():
    summary = SoftwareService._safe_summary({
        "api_key": "api-secret", "nested": {"refreshToken": "refresh-secret"},
        "message": "Authorization: Bearer live-secret",
    })
    assert "api-secret" not in summary
    assert "refresh-secret" not in summary
    assert "live-secret" not in summary
    assert summary.count("[REDACTED]") == 3
