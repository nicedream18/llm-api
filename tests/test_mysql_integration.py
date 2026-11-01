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
    not os.environ.get("WALIAPI_TEST_MYSQL_SOCKET"),
    reason="Set WALIAPI_TEST_MYSQL_SOCKET to an isolated MySQL test server",
)


@pytest.fixture
def mysql_engine(monkeypatch):
    socket = os.environ["WALIAPI_TEST_MYSQL_SOCKET"]
    database = "waliapi_test_" + uuid.uuid4().hex
    url = URL.create(
        "mysql+pymysql",
        username="root",
        query={"unix_socket": socket, "charset": "utf8mb4"},
    )
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
