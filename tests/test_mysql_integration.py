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
