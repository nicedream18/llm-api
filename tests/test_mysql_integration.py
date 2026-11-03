"""Opt-in MySQL tests against an isolated test server.

Set WALIAPI_TEST_MYSQL_SOCKET to its Unix socket. Each test creates and drops
its own randomly named database; the application's configured DB is never used.
"""

import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import URL, create_engine, text

from app.application.services.wiki_service import WikiService
from app.infrastructure.database import migrations
from app.infrastructure.repositories.wiki_repo import WikiRepository
from app.types.wiki import WikiBackup, WikiPageInput

pytestmark = pytest.mark.skipif(
    not (os.environ.get("WALIAPI_TEST_MYSQL_SOCKET") or os.environ.get("WALIAPI_TEST_MYSQL_HOST")),
    reason="Set WALIAPI_TEST_MYSQL_SOCKET or WALIAPI_TEST_MYSQL_HOST to an isolated MySQL test server",
)


@pytest.fixture
def mysql_engine(monkeypatch):
    socket = os.environ.get("WALIAPI_TEST_MYSQL_SOCKET")
    host = os.environ.get("WALIAPI_TEST_MYSQL_HOST", "127.0.0.1")
    port = int(os.environ.get("WALIAPI_TEST_MYSQL_PORT", "3306"))
    username = os.environ.get("WALIAPI_TEST_MYSQL_USER", "root")
    password = os.environ.get("WALIAPI_TEST_MYSQL_PASSWORD", "")
    database = "waliapi_test_" + uuid.uuid4().hex
    query = {"charset": "utf8mb4"}
    if socket:
        query["unix_socket"] = socket
        url = URL.create("mysql+pymysql", username=username, password=password, query=query)
    else:
        url = URL.create("mysql+pymysql", username=username, password=password, host=host, port=port, query=query)
    admin_engine = create_engine(url)
    with admin_engine.begin() as db:
        db.execute(
            text(
                f"CREATE DATABASE {database} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    engine = create_engine(url.set(database=database))
    try:
        with engine.begin() as db:
            for statement in migrations.sql_statements(
                Path("docs/waliapi.sql").read_text()
            ):
                if statement.upper().startswith(("CREATE DATABASE", "USE ")):
                    continue
                db.execute(text(statement))
        monkeypatch.setattr(migrations, "engine", engine)
        monkeypatch.setattr(
            migrations,
            "config",
            replace(
                migrations.config,
                auth=replace(
                    migrations.config.auth,
                    bootstrap_password="",
                    admin_password_hash="",
                ),
            ),
        )
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as db:
            db.execute(text(f"DROP DATABASE {database}"))
        admin_engine.dispose()


def test_mysql_full_migration_upgrade_is_idempotent(mysql_engine):
    migrations.apply_migrations()
    migrations.apply_migrations()
    assert migrations.validate()
    rows = migrations.status()
    assert len(rows) == len(migrations.migration_files())
    assert all(row["applied"] and row["checksum_valid"] for row in rows)
    with mysql_engine.begin() as db:
        db.execute(
            text(
                "UPDATE schema_migrations SET checksum=:checksum WHERE version='009_wiki'"
            ),
            {"checksum": "0" * 64},
        )
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrations.apply_migrations()


@pytest.mark.parametrize("user_collation,session_collation", [
    ("utf8mb4_0900_ai_ci", "utf8mb4_unicode_ci"),
    ("utf8mb4_unicode_ci", "utf8mb4_0900_ai_ci"),
])
def test_mysql_admin_page_with_mixed_session_collations(mysql_engine, monkeypatch, user_collation, session_collation):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient

    from app.api.controllers import auth_routes
    from app.api.middleware.auth import ApiKeyAuthMiddleware
    from app.application.services.admin_service import AdminService
    from app.application.services.auth_service import hash_password
    from app.config import config
    from app.infrastructure.repositories.admin_session_repo import (
        AdminSessionRepository,
    )

    migrations.apply_migrations()
    username = config.auth.admin_username
    with mysql_engine.begin() as db:
        # Reproduce installations whose existing tables use server defaults
        # that differ from the migration-created session tables.
        db.execute(text(f"ALTER TABLE admin_users CONVERT TO CHARACTER SET utf8mb4 COLLATE {user_collation}"))
        db.execute(text(f"ALTER TABLE admin_sessions CONVERT TO CHARACTER SET utf8mb4 COLLATE {session_collation}"))
        db.execute(text("""INSERT INTO admin_users (id,username,password_hash,status,created_at,updated_at)
            VALUES ('test-admin',:username,:hash,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())"""),
                   {"username": username, "hash": hash_password("test-admin-password")})
    sessions = AdminSessionRepository(mysql_engine)
    service = AdminService(SimpleNamespace(write_audit=lambda *args: None), sessions)
    container = SimpleNamespace(admin_service=service, channel_repo=None)
    monkeypatch.setattr("app.api.middleware.auth.get_container", lambda: container)
    monkeypatch.setattr(auth_routes, "get_container", lambda: container)
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.add_middleware(ApiKeyAuthMiddleware)
    app.mount("/", StaticFiles(directory="app/static", html=True))
    with TestClient(app) as client:
        assert client.get("/admin/").status_code == 200
        client.cookies.set("waliapi_admin_session", "legacy.signed-cookie")
        assert client.get("/admin/").status_code == 200
        assert client.get("/api/v1/auth/session").status_code == 401
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "test-admin-password"})
        assert login.status_code == 200
        token = login.cookies["waliapi_admin_session"]
        client.cookies.clear()
        client.cookies.set("waliapi_admin_session", token)
        assert client.get("/admin/").status_code == 200
        assert client.get("/api/v1/auth/session").json()["data"]["authenticated"]
        assert client.post("/api/v1/auth/logout").status_code == 200
        client.cookies.clear()
        client.cookies.set("waliapi_admin_session", token)
        assert client.get("/admin/").status_code == 200
        assert client.get("/api/v1/auth/session").status_code == 401


def test_mysql_wiki_transactions_cascade_and_backup(mysql_engine):
    migrations.apply_migrations()
    service = WikiService(WikiRepository(mysql_engine))
    project = service.repo.create_project({"name": "真实 MySQL", "description": ""})
    first = service.create_page(
        project["id"],
        WikiPageInput(path="中文/页面.md", title="中文页面", content="正文 #标签"),
    )
    source = service.repo.create_source(
        project["id"], {"filename": "source.md", "content": "内容"}
    )
    service.ingest(project["id"], source["id"])
    service.repo.add_attachment(
        project["id"], first["id"], "中文.txt", "text/plain", b"contents"
    )
    restored = service.restore(WikiBackup.model_validate(service.export(project["id"])))
    assert service.list_pages(restored["id"])[0]["content"]
    service.repo.delete_project(project["id"])
    with mysql_engine.connect() as db:
        assert (
            db.execute(
                text("SELECT COUNT(*) FROM wiki_sources WHERE project_id=:id"),
                {"id": project["id"]},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                text("SELECT COUNT(*) FROM wiki_attachments WHERE project_id=:id"),
                {"id": project["id"]},
            ).scalar_one()
            == 0
        )


def test_mysql_migration_lock_and_quota_accounting(mysql_engine, monkeypatch):
    migrations.apply_migrations()
    with mysql_engine.connect() as holder:
        assert holder.execute(text("SELECT GET_LOCK('waliapi_schema_migrations', 0)")).scalar_one() == 1
        with pytest.raises(RuntimeError, match="Could not acquire schema migration lock"):
            migrations.apply_migrations()
        holder.execute(text("SELECT RELEASE_LOCK('waliapi_schema_migrations')"))

    from contextlib import contextmanager

    from app.infrastructure.repositories import quota_repo
    from app.infrastructure.repositories.quota_repo import QuotaRepository

    @contextmanager
    def mysql_db():
        with mysql_engine.begin() as db:
            yield db

    monkeypatch.setattr(quota_repo, "get_db", mysql_db)
    key_id = "mysql-quota-key"
    with mysql_engine.begin() as db:
        db.execute(
            text("""INSERT INTO api_keys
                (id, name, `key`, status, allowed_models, allowed_channels, quota_limit, quota_used, created_at, updated_at)
                VALUES (:id, 'quota', :key, 1, '[]', '[]', 100, 0, UTC_TIMESTAMP(), UTC_TIMESTAMP())"""),
            {"id": key_id, "key": "mysql-quota-secret"},
        )

    repo = QuotaRepository()
    reservation = repo.reserve(key_id, "mysql-request-1", 80)
    assert reservation
    assert repo.reserve(key_id, "mysql-request-1", 80) == reservation
    assert repo.reserve(key_id, "mysql-request-2", 30) is None
    assert repo.settle(reservation, 50) is True
    assert repo.settle(reservation, 20) is False
    with mysql_engine.connect() as db:
        row = db.execute(text("SELECT quota_used FROM api_keys WHERE id=:id"), {"id": key_id}).scalar_one()
        assert row == 50


def test_mysql_provider_account_operations(mysql_engine):
    from app.application.services.provider_service import ProviderService
    from app.infrastructure.repositories.provider_repo import ProviderRepository
    from app.types.provider import (
        ProviderAccountInput,
        ProviderAccountQuery,
        ProviderOperationInput,
        ProviderTokenInput,
    )

    migrations.apply_migrations()
    service = ProviderService(ProviderRepository(mysql_engine))
    account_id = service.create_account(ProviderAccountInput(provider="codex", name="MySQL account"))["id"]
    service.set_token(account_id, ProviderTokenInput(access_token="synthetic-test-token"))
    service.operate_account(account_id, ProviderOperationInput(operation="tags", tags=["a%b_"]))
    assert service.query_accounts(ProviderAccountQuery(tag="a%b_"))["total"] == 1
    service.operate_account(account_id, ProviderOperationInput(operation="archive"))
    assert service.repo.get_token(account_id) is None
    assert service.query_accounts(ProviderAccountQuery(archived=True))["total"] == 1
    service.operate_account(account_id, ProviderOperationInput(operation="restore"))
    assert service.repo.get_token(account_id) is None


def test_mysql_provider_refresh_lease_and_epoch(mysql_engine):
    from app.application.errors import ApplicationError
    from app.infrastructure.repositories.provider_repo import ProviderRepository

    migrations.apply_migrations()
    first, second = ProviderRepository(mysql_engine), ProviderRepository(mysql_engine)
    account = first.create_account({"provider": "codex", "name": "lease", "priority": 0})["id"]
    values = {"access_token": "synthetic-cipher", "refresh_token": None, "expires_at": None}
    first.save_token(account, values)
    leased = first.claim_refresh(account, "worker-one")
    with pytest.raises(ApplicationError) as conflict:
        second.claim_refresh(account, "worker-two")
    assert conflict.value.code == "refresh_in_progress"
    second.delete_token(account)
    with pytest.raises(ApplicationError) as stale:
        first.store_token(account, values, leased["generation"], "worker-one")
    assert stale.value.code == "authorization_changed"
    assert second.get_token(account) is None


def test_mysql_provider_sync_jobs_and_snapshot_fencing(mysql_engine):
    from app.infrastructure.repositories.provider_repo import ProviderRepository

    migrations.apply_migrations()
    first, second = ProviderRepository(mysql_engine), ProviderRepository(mysql_engine)
    account = first.create_account({"provider": "codex", "name": "sync", "priority": 0})["id"]
    first.save_token(account, {"access_token": "synthetic-cipher", "refresh_token": None, "expires_at": None})
    first.update_account(account, {"status": "active"})
    job_id = first.enqueue_sync(account, "quota")["id"]
    assert second.enqueue_sync(account, "quota")["id"] == job_id
    job = first.claim_sync("one")
    assert second.claim_sync("two") is None
    _, _, generation = first.read_sync_credentials(account)
    assert first.save_snapshot(account, "quota", generation, {"windows": []}, job=job)
    assert first.finish_sync(job)
    assert not second.finish_sync(job)
    first.delete_account(account)
    with mysql_engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM provider_sync_jobs")).scalar_one() == 0
        assert db.execute(text("SELECT COUNT(*) FROM provider_snapshots")).scalar_one() == 0


def test_mysql_route_capacity_and_half_open_probe(mysql_engine):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.repositories.routing_repo import RoutingRepository
    from app.types.routing import RoutePolicy

    migrations.apply_migrations()
    repo = RoutingRepository(mysql_engine)
    repo.save_policy("test", RoutePolicy(max_concurrent=1).model_dump())
    repo.save_policy("test", RoutePolicy(max_concurrent=2).model_dump())
    assert repo.policy("test")["max_concurrent"] == 2
    with ThreadPoolExecutor(max_workers=4) as pool:
        leases = [lease for lease in pool.map(lambda _: repo.acquire("channel", 2), range(8)) if lease]
    assert len(leases) == 2
    assert repo.finish(leases[0], failure=True)
    assert repo.finish(leases[1], success=True)
    assert repo.acquire("channel") is None
    with mysql_engine.begin() as db:
        db.execute(text("UPDATE route_runtime SET cooldown_until='2000-01-01'"))
    probe = repo.acquire("channel")
    assert probe and repo.acquire("channel") is None
    assert repo.finish(probe, success=True)


def test_mysql_usage_ledger_deduplication_and_decimal_prices(mysql_engine):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.repositories.usage_repo import UsageRepository
    from app.types.usage import PriceInput, UsageFact

    migrations.apply_migrations()
    repo = UsageRepository(mysql_engine)
    repo.add_price(PriceInput(provider="test", model="demo", currency="USD", input_per_million="0.125", output_per_million="0.375", effective_at="2026-01-01T00:00:00Z"))
    value = UsageFact(execution_id="mysql", event_key="attempt:1", request_id="trace", kind="attempt", provider="test", model="demo", endpoint="/v1/chat/completions", outcome="succeeded", input_tokens=3, output_tokens=7, total_tokens=10, usage_source="reported", occurred_at="2026-11-02T00:00:00+00:00")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: repo.append(value), range(8))) == 1
    assert repo.execution("mysql")[0]["cost"] == "0.000003"


def test_mysql_operational_alert_deduplication_and_analytics(mysql_engine):
    from concurrent.futures import ThreadPoolExecutor

    from app.infrastructure.repositories.alert_repo import AlertRepository
    from app.infrastructure.repositories.analytics_repo import AnalyticsRepository
    from app.types.analytics import AlertRule, AnalyticsQuery

    migrations.apply_migrations()
    repo = AlertRepository(mysql_engine)
    repo.save_rule("failure", AlertRule(metric="failure_rate", threshold=0.1).model_dump())
    repo.save_rule("failure", AlertRule(metric="failure_rate", threshold=0.2).model_dump())
    assert repo.rules()[0]["threshold"] == 0.2
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: repo.transition("failure:provider", True), range(8)))
    assert len(set(ids)) == 1
    assert repo.acknowledge(ids[0], "admin")
    assert not AnalyticsRepository(mysql_engine).report(AnalyticsQuery())["items"]


def test_mysql_knowledge_publication_fences_expired_workers(mysql_engine, monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy.orm import Session

    from app.domain.entities import (
        KbChunkEntity,
        KbDocumentEntity,
        KbKnowledgeBaseEntity,
        KbTaskEntity,
    )
    from app.domain.task_lease import LostTaskLease, TaskLease
    from app.infrastructure.repositories.kb_repo import KbRepository

    migrations.apply_migrations()
    @contextmanager
    def mysql_db():
        with Session(mysql_engine) as db, db.begin():
            yield db
    monkeypatch.setattr("app.infrastructure.repositories.kb_repo.get_db", mysql_db)
    repo = KbRepository()
    repo.save_kb(KbKnowledgeBaseEntity(id="fence-kb", name="Fencing"))
    repo.save_doc(KbDocumentEntity(id="fence-doc", kb_id="fence-kb", name="test.txt", status="pending"))
    repo.save_task(KbTaskEntity(id="fence-task", kb_id="fence-kb", doc_id="fence-doc", task_type="import"))
    assert repo.claim_next_task("old", 60)
    with mysql_engine.begin() as db:
        db.execute(text("UPDATE kb_tasks SET lease_until='2000-01-01' WHERE id='fence-task'"))
    repo.recover_expired_tasks()
    claimed = repo.claim_next_task("new", 60)
    values = [KbChunkEntity(id="fence-chunk", kb_id="fence-kb", doc_id="fence-doc", content="new", token_count=3)]
    old = TaskLease("old", 1)
    with pytest.raises(LostTaskLease):
        repo.publish_document("fence-task", old, "fence-kb", "fence-doc", values)
    assert not repo.fail_or_retry_task("fence-task", "old failure", 1, old)
    current = TaskLease("new", claimed["attempt_count"])
    repo.publish_document("fence-task", current, "fence-kb", "fence-doc", values)
    with pytest.raises(LostTaskLease):
        repo.publish_document("fence-task", current, "fence-kb", "fence-doc", values)
    assert repo.find_kb_by_id("fence-kb").chunk_count == 1
    assert repo.find_task_by_id("fence-task").status == "completed"
