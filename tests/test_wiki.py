import base64
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.pool import StaticPool

from app.application.errors import ApplicationError
from app.application.services.wiki_service import WikiService, prose
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.wiki_repo import WikiRepository
from app.types.wiki import WikiBackup, WikiPageInput, WikiPageUpdate


@pytest.fixture
def wiki():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/009_wiki.sql"))
        execute_migration(db, Path("docs/migrations/009_wiki.sql"))
        execute_migration(db, Path("docs/migrations/010_access_grants.sql"))
    service = WikiService(WikiRepository(engine))
    yield service
    engine.dispose()


def project(wiki, name="Project"):
    return wiki.repo.create_project({"name": name, "description": "Knowledge"})


def page(wiki, project_id, path="guide/start.md", content="Text #python"):
    return wiki.create_page(
        project_id, WikiPageInput(path=path, title=path, content=content)
    )


def test_project_and_page_persistence_and_revision_conflicts(wiki):
    proj = project(wiki)
    assert wiki.repo.list_projects()[0]["id"] == proj["id"]
    wiki.repo.update_project(proj["id"], {"name": "Edited", "description": ""})
    assert wiki.repo.get_project(proj["id"])["name"] == "Edited"
    first = page(wiki, proj["id"])
    assert first["revision"] == 1 and first["tags"] == ["python"]
    update = WikiPageUpdate(
        path="guide/new.md", title="New", content="Updated", revision=1
    )
    changed = wiki.update_page(proj["id"], first["id"], update)
    assert changed["revision"] == 2
    with pytest.raises(ApplicationError) as error:
        wiki.update_page(proj["id"], first["id"], update)
    assert error.value.status_code == 409
    assert wiki.repo.get_page(proj["id"], first["id"])["content"] == "Updated"


def test_uniqueness_and_project_boundaries(wiki):
    a, b = project(wiki, "A"), project(wiki, "B")
    first = page(wiki, a["id"])
    with pytest.raises(ApplicationError) as error:
        page(wiki, a["id"])
    assert error.value.code == "path_conflict"
    page(wiki, b["id"])
    with pytest.raises(ApplicationError) as error:
        wiki.repo.get_page(b["id"], first["id"])
    assert error.value.status_code == 404
    with pytest.raises(ApplicationError):
        wiki.repo.delete_page(b["id"], first["id"])
    assert wiki.repo.get_page(a["id"], first["id"])


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/root",
        "../page",
        "dir/../page",
        "a//b",
        "a/./b",
        "a\\b",
        "a\x00b",
        "x" * 385,
    ],
)
def test_invalid_paths_are_rejected(path):
    with pytest.raises(ValidationError):
        WikiPageInput(path=path, title="Title")


def test_tag_extraction_and_search_ignore_code(wiki):
    proj = project(wiki)
    content = (
        "Hello #python #中文\n   ~~~python\n#private [[missing]]\n   ~~~\n `#hidden`"
    )
    row = page(wiki, proj["id"], content=content)
    assert row["tags"] == ["python", "中文"]
    assert "#private" not in prose(content)
    assert wiki.tags(proj["id"]) == [
        {"tag": "python", "count": 1},
        {"tag": "中文", "count": 1},
    ]
    assert len(wiki.list_pages(proj["id"], query="HELLO", tag="python")) == 1
    assert wiki.list_pages(proj["id"], query="absent") == []


def test_graph_resolves_relative_links_aliases_and_dangling_nodes(wiki):
    proj = project(wiki)
    first = page(
        wiki,
        proj["id"],
        path="guide/a.md",
        content="[[b|Label]] [[guide/b.md#part]] [[absent]]",
    )
    second = page(wiki, proj["id"], path="guide/b.md")
    graph = wiki.graph(proj["id"])
    assert len(graph["nodes"]) == 2
    assert [edge["target"] for edge in graph["edges"]] == [
        second["id"],
        second["id"],
        None,
    ]
    assert all(edge["source"] == first["id"] for edge in graph["edges"])


def test_source_ingestion_is_persistent_and_reingestion_updates_page(wiki):
    proj = project(wiki)
    source = wiki.repo.create_source(
        proj["id"], {"filename": "notes.md", "content": "Notes #wiki"}
    )
    assert source["status"] == "pending"
    ingested = wiki.ingest(proj["id"], source["id"])
    assert wiki.repo.list_sources(proj["id"])[0]["status"] == "ingested"
    repeated = wiki.ingest(proj["id"], source["id"])
    assert repeated["id"] == ingested["id"] and repeated["revision"] == 2
    wiki.repo.delete_source(proj["id"], source["id"])
    assert wiki.repo.get_page(proj["id"], ingested["id"])


def test_failed_source_does_not_leave_partial_pages(wiki):
    proj = project(wiki)
    source = wiki.repo.create_source(
        proj["id"], {"filename": "notes.exe", "content": "binary"}
    )
    with pytest.raises(ApplicationError):
        wiki.ingest(proj["id"], source["id"])
    assert wiki.repo.list_sources(proj["id"])[0]["status"] == "failed"
    assert wiki.repo.list_pages(proj["id"]) == []


def test_backup_roundtrip_preserves_pages_assets_sources(wiki):
    proj = project(wiki)
    first = page(wiki, proj["id"])
    wiki.repo.create_source(proj["id"], {"filename": "notes.txt", "content": "Notes"})
    asset = wiki.repo.add_attachment(
        proj["id"], first["id"], "diagram.png", "image/png", b"png"
    )
    snapshot = wiki.export(proj["id"])
    assert (
        snapshot["attachments"][0]["content_base64"]
        == base64.b64encode(b"png").decode()
    )
    restored = wiki.restore(WikiBackup.model_validate(snapshot))
    assert restored["id"] != proj["id"]
    assert wiki.list_pages(restored["id"])[0]["content"] == first["content"]
    assert wiki.export(restored["id"])["attachments"] == snapshot["attachments"]
    wiki.repo.delete_project(proj["id"])
    with pytest.raises(ApplicationError):
        wiki.repo.get_attachment(proj["id"], asset["id"])
    with wiki.repo.engine.connect() as db:
        assert (
            db.execute(
                text("SELECT COUNT(*) FROM wiki_pages WHERE project_id=:id"),
                {"id": proj["id"]},
            ).scalar_one()
            == 0
        )


def test_invalid_backup_does_not_create_project(wiki):
    proj = project(wiki)
    page(wiki, proj["id"])
    backup = wiki.export(proj["id"])
    backup["pages"].append(backup["pages"][0].copy())
    with pytest.raises(ApplicationError):
        wiki.restore(WikiBackup.model_validate(backup))
    assert len(wiki.repo.list_projects()) == 1
    backup["pages"].pop()
    backup["attachments"] = [
        {
            "page_path": "absent.md",
            "filename": "a.txt",
            "media_type": "text/plain",
            "content_base64": "eA==",
        }
    ]
    with pytest.raises(ApplicationError):
        wiki.restore(WikiBackup.model_validate(backup))
    assert len(wiki.repo.list_projects()) == 1


def test_asset_restrictions():
    for filename, media_type, content in [
        ("../x", "text/plain", b"x"),
        ("x", "text/html", b"x"),
        ("x", "text/plain", b""),
    ]:
        with pytest.raises(ApplicationError):
            WikiService.validate_asset(filename, media_type, content)


def test_actual_migration_has_expected_tables(wiki):
    tables = set(inspect(wiki.repo.engine).get_table_names())
    assert {"wiki_projects", "wiki_pages", "wiki_sources", "wiki_attachments"}.issubset(
        tables
    )


@pytest.fixture
def wiki_client(wiki, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from unittest.mock import Mock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.controllers.access_routes import router as access_router
    from app.api.controllers.wiki_routes import router
    from app.api.error_handlers import application_error_handler
    from app.api.middleware.auth import ApiKeyAuthMiddleware
    from app.application.services.access_service import AccessService
    from app.config import config
    from app.domain.entities import ApiKeyEntity
    from app.infrastructure.repositories.access_repo import AccessRepository

    container = SimpleNamespace(
        wiki_service=wiki,
        channel_repo=Mock(),
        access_service=AccessService(AccessRepository(wiki.repo.engine)),
    )
    container.channel_repo.get_api_key_by_key.side_effect = lambda token: (
        ApiKeyEntity(id="wiki-key", name="Read only", status=1)
        if token == "wiki-readonly"
        else None
    )

    test_config = replace(
        config,
        auth=replace(
            config.auth, admin_token="wiki-test-admin", mcp_token="wiki-test-mcp"
        ),
    )
    for module in ("app.api.middleware.auth", "app.application.services.auth_service"):
        monkeypatch.setattr(f"{module}.config", test_config)
    for module in (
        "app.api.middleware.auth",
        "app.api.controllers.wiki_routes",
        "app.api.controllers.access_routes",
    ):
        monkeypatch.setattr(f"{module}.get_container", lambda: container)
    app = FastAPI()
    app.include_router(router)
    app.include_router(access_router)
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_middleware(ApiKeyAuthMiddleware)
    return TestClient(app, headers={"Authorization": "Bearer wiki-test-admin"})


def test_management_routes_reject_unauthorized_and_mcp_credentials(wiki_client):
    for token in ("", "wiki-test-mcp", "invalid"):
        response = wiki_client.get(
            "/api/v1/wiki/projects", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401


def test_http_wiki_workflow_and_restore(wiki_client):
    base = "/api/v1/wiki"
    response = wiki_client.post(base + "/projects", json={"name": "HTTP Wiki"})
    assert response.status_code == 201
    project_id = response.json()["data"]["id"]
    path = base + "/projects/" + project_id
    created = wiki_client.post(
        path + "/pages",
        json={
            "path": "guide.md",
            "title": "Guide",
            "content": "Hello #http",
        },
    )
    assert created.status_code == 201
    page_id = created.json()["data"]["id"]
    pages = wiki_client.get(
        path + "/pages", params={"tag": "http", "query": "hello"}
    ).json()["data"]
    assert pages["total"] == 1 and pages["items"][0]["id"] == page_id
    for revision, expected_status in ((1, 200), (1, 409)):
        response = wiki_client.put(
            path + "/pages/" + page_id,
            json={
                "path": "guide.md",
                "title": "Guide",
                "content": "Updated",
                "revision": revision,
            },
        )
        assert response.status_code == expected_status
    upload = wiki_client.post(
        path + "/pages/" + page_id + "/attachments",
        params={"filename": "notes.txt"},
        content=b"safe text",
        headers={"Content-Type": "text/plain"},
    )
    assert upload.status_code == 201
    attachment_id = upload.json()["data"]["id"]
    download = wiki_client.get(path + "/attachments/" + attachment_id)
    assert download.content == b"safe text"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert download.headers["content-disposition"].startswith("attachment;")
    snapshot = wiki_client.get(path + "/backup").json()
    restored = wiki_client.post(base + "/restore", json=snapshot)
    assert restored.status_code == 201
    assert restored.json()["data"]["id"] != project_id
    source = wiki_client.post(
        path + "/sources", json={"filename": "a.md", "content": "source text"}
    ).json()["data"]
    assert source["status"] == "pending" and "content" not in source
    assert (
        wiki_client.post(path + "/sources/" + source["id"] + "/ingest").status_code
        == 200
    )
    assert wiki_client.get(path + "/sources").json()["data"][0]["status"] == "ingested"
    assert wiki_client.delete(path).status_code == 200
    assert wiki_client.get(path).status_code == 404


def test_http_validation_and_payload_limits(wiki_client, monkeypatch):
    root = "/api/v1/wiki"
    proj = wiki_client.post(root + "/projects", json={"name": "Validation"}).json()[
        "data"
    ]["id"]
    path = root + "/projects/" + proj
    assert (
        wiki_client.post(
            path + "/pages", json={"path": "../bad", "title": "bad"}
        ).status_code
        == 422
    )
    assert wiki_client.get(path + "/pages?limit=0").status_code == 422
    page_id = wiki_client.post(
        path + "/pages", json={"path": "a.md", "title": "A"}
    ).json()["data"]["id"]
    monkeypatch.setattr("app.api.controllers.wiki_routes.MAX_ASSET_BYTES", 4)
    upload = path + "/pages/" + page_id + "/attachments?filename=x.txt"
    assert (
        wiki_client.post(
            upload, content=b"12345", headers={"Content-Type": "text/plain"}
        ).status_code
        == 413
    )
    assert (
        wiki_client.post(
            upload, content=b"x", headers={"Content-Type": "text/html"}
        ).status_code
        == 415
    )
    assert wiki_client.post(root + "/restore", content=b"{").status_code == 422


def test_backup_restores_ingestion_links_without_duplicate_pages(wiki):
    proj = project(wiki)
    source = wiki.repo.create_source(
        proj["id"], {"filename": "notes.md", "content": "Linked"}
    )
    first = wiki.ingest(proj["id"], source["id"])
    restored = wiki.restore(WikiBackup.model_validate(wiki.export(proj["id"])))
    restored_source = wiki.repo.list_sources(restored["id"])[0]
    assert restored_source["status"] == "ingested"
    linked_page = wiki.repo.get_page(restored["id"], restored_source["page_id"])
    assert linked_page["path"] == first["path"]
    updated = wiki.ingest(restored["id"], restored_source["id"])
    assert updated["id"] == linked_page["id"] and updated["path"] == first["path"]
    assert len(wiki.repo.list_pages(restored["id"])) == 1


def test_deleting_ingested_page_resets_source_and_keeps_backup_restorable(wiki):
    proj = project(wiki)
    source = wiki.repo.create_source(
        proj["id"], {"filename": "notes.md", "content": "Notes"}
    )
    first = wiki.ingest(proj["id"], source["id"])
    wiki.repo.delete_page(proj["id"], first["id"])
    remaining = wiki.repo.list_sources(proj["id"])[0]
    assert remaining["status"] == "pending" and remaining["page_id"] is None
    assert wiki.restore(WikiBackup.model_validate(wiki.export(proj["id"])))
    new_page = wiki.ingest(proj["id"], source["id"])
    assert new_page["id"] != first["id"]


def test_question_uses_project_evidence_and_preserves_auth_context(wiki):
    import json
    from unittest.mock import Mock

    from app.types.auth import AuthContext
    from app.types.wiki import WikiAskInput

    a, b = project(wiki, "A"), project(wiki, "B")
    page(wiki, a["id"], content="Python gateway facts")
    page(wiki, b["id"], content="Python private other project")
    wiki.proxy = Mock()
    wiki.proxy.forward.return_value = (
        200,
        {
            "choices": [{"message": {"content": "Grounded answer"}}],
            "usage": {"total_tokens": 10},
        },
    )
    auth = AuthContext("api_key", "limited")
    response = wiki.ask(
        a["id"], WikiAskInput(question="Python", model="test-model"), auth, "request-1"
    )
    assert response["answer"] == "Grounded answer" and len(response["sources"]) == 1
    body = json.loads(wiki.proxy.forward.call_args.args[0])
    assert "private other project" not in json.dumps(body)
    assert wiki.proxy.forward.call_args.kwargs["auth_context"] == auth
    assert wiki.proxy.forward.call_args.kwargs["request_id"] == "request-1"
    wiki.proxy.reset_mock()
    empty = wiki.ask(a["id"], WikiAskInput(question="unfindable", model="test-model"))
    assert empty["sources"] == []
    wiki.proxy.forward.assert_not_called()


def test_upstream_answer_errors_are_safe(wiki):
    from unittest.mock import Mock

    from app.types.wiki import WikiAskInput

    proj = project(wiki)
    page(wiki, proj["id"], content="Python")
    wiki.proxy = Mock()
    for result in ((502, {"private": "details"}), (200, {"choices": []})):
        wiki.proxy.forward.return_value = result
        with pytest.raises(ApplicationError):
            wiki.ask(proj["id"], WikiAskInput(question="Python", model="model"))


def test_project_grants_filter_lists_and_prevent_cross_project_reads(wiki_client):
    root = "/api/v1/wiki/projects"
    a = wiki_client.post(root, json={"name": "Visible"}).json()["data"]
    b = wiki_client.post(root, json={"name": "Private"}).json()["data"]
    headers = {"Authorization": "Bearer wiki-readonly"}
    assert wiki_client.get(root, headers=headers).json()["data"] == []
    assert wiki_client.get(root + "/" + a["id"], headers=headers).status_code == 403
    grant = wiki_client.post(
        "/api/v1/access/grants",
        json={
            "principal_type": "api_key",
            "principal_id": "wiki-key",
            "resource_type": "wiki",
            "resource_id": a["id"],
            "action": "read",
        },
    )
    assert grant.status_code == 201
    assert wiki_client.get(root, headers=headers).json()["data"] == [a]
    assert wiki_client.get(root + "/" + a["id"], headers=headers).status_code == 200
    assert (
        wiki_client.get(root + "/" + b["id"] + "/pages", headers=headers).status_code
        == 403
    )
    assert (
        wiki_client.post(
            root + "/" + a["id"] + "/pages",
            headers=headers,
            json={
                "path": "bad.md",
                "title": "Write forbidden",
            },
        ).status_code
        == 403
    )
    assert wiki_client.get("/api/v1/access/grants", headers=headers).status_code == 401
    wiki_client.delete("/api/v1/access/grants/" + grant.json()["data"]["id"])
    assert wiki_client.get(root + "/" + a["id"], headers=headers).status_code == 403
