"""Transactional Wiki persistence, with optimistic concurrency for page edits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    delete,
    insert,
    select,
    update,
)

from app.application.errors import ApplicationError
from app.infrastructure.database.connection import engine as default_engine

metadata = MetaData()
projects = Table(
    "wiki_projects",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("description", Text, nullable=False),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)
pages = Table(
    "wiki_pages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("wiki_projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("path", String(384), nullable=False),
    Column("title", String(256), nullable=False),
    Column("content", Text, nullable=False),
    Column("tags", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
    UniqueConstraint("project_id", "path"),
)
sources = Table(
    "wiki_sources",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("wiki_projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("filename", String(256), nullable=False),
    Column("content", Text, nullable=False),
    Column("status", String(16), nullable=False),
    Column("page_id", String(64), ForeignKey("wiki_pages.id", ondelete="SET NULL")),
    Column("error_message", Text),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)
attachments = Table(
    "wiki_attachments",
    metadata,
    Column("id", String(64), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("wiki_projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "page_id",
        String(64),
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("filename", String(256), nullable=False),
    Column("media_type", String(128), nullable=False),
    Column("content", LargeBinary, nullable=False),
    Column("created_at", String(32), nullable=False),
)


def new_record(**values):
    now = datetime.now(UTC).isoformat()
    return {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now, **values}


class WikiRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def list_projects(self):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(projects).order_by(projects.c.created_at, projects.c.id)
                ).mappings()
            ]

    def get_project(self, project_id):
        with self.engine.connect() as db:
            row = (
                db.execute(select(projects).where(projects.c.id == project_id))
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("Wiki project not found", 404, "not_found")
            return dict(row)

    def create_project(self, values):
        row = new_record(**values)
        with self.engine.begin() as db:
            db.execute(insert(projects), row)
        return row

    def update_project(self, project_id, values):
        self.get_project(project_id)
        with self.engine.begin() as db:
            db.execute(
                update(projects)
                .where(projects.c.id == project_id)
                .values(**values, updated_at=datetime.now(UTC).isoformat())
            )
        return self.get_project(project_id)

    def delete_project(self, project_id):
        with self.engine.begin() as db:
            if (
                db.execute(delete(projects).where(projects.c.id == project_id)).rowcount
                != 1
            ):
                raise ApplicationError("Wiki project not found", 404, "not_found")

    def list_pages(self, project_id):
        self.get_project(project_id)
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(pages)
                    .where(pages.c.project_id == project_id)
                    .order_by(pages.c.path)
                ).mappings()
            ]

    def get_page(self, project_id, page_id):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(pages).where(
                        pages.c.project_id == project_id, pages.c.id == page_id
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("Wiki page not found", 404, "not_found")
            return dict(row)

    def create_page(self, project_id, values):
        self.get_project(project_id)
        row = new_record(project_id=project_id, revision=1, **values)
        with self.engine.begin() as db:
            db.execute(insert(pages), row)
        return row

    def update_page(self, project_id, page_id, values, revision):
        with self.engine.begin() as db:
            result = db.execute(
                update(pages)
                .where(
                    pages.c.project_id == project_id,
                    pages.c.id == page_id,
                    pages.c.revision == revision,
                )
                .values(
                    **values,
                    revision=revision + 1,
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )
            if result.rowcount != 1:
                exists = db.execute(
                    select(pages.c.id).where(
                        pages.c.id == page_id, pages.c.project_id == project_id
                    )
                ).first()
                raise ApplicationError(
                    "Page revision conflict" if exists else "Wiki page not found",
                    409 if exists else 404,
                    "revision_conflict" if exists else "not_found",
                )
        return self.get_page(project_id, page_id)

    def delete_page(self, project_id, page_id):
        with self.engine.begin() as db:
            db.execute(
                update(sources)
                .where(sources.c.project_id == project_id, sources.c.page_id == page_id)
                .values(
                    status="pending",
                    page_id=None,
                    error_message=None,
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )
            if (
                db.execute(
                    delete(pages).where(
                        pages.c.project_id == project_id, pages.c.id == page_id
                    )
                ).rowcount
                != 1
            ):
                raise ApplicationError("Wiki page not found", 404, "not_found")

    def list_sources(self, project_id):
        self.get_project(project_id)
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    select(sources)
                    .where(sources.c.project_id == project_id)
                    .order_by(sources.c.created_at, sources.c.id)
                ).mappings()
            ]

    def create_source(self, project_id, values):
        self.get_project(project_id)
        row = new_record(
            project_id=project_id,
            status="pending",
            page_id=None,
            error_message=None,
            **values,
        )
        with self.engine.begin() as db:
            db.execute(insert(sources), row)
        return row

    def delete_source(self, project_id, source_id):
        with self.engine.begin() as db:
            if (
                db.execute(
                    delete(sources).where(
                        sources.c.project_id == project_id, sources.c.id == source_id
                    )
                ).rowcount
                != 1
            ):
                raise ApplicationError("Wiki source not found", 404, "not_found")

    def ingest_source(self, project_id, source_id, make_page):
        """Serialize ingestion on the source row; commit page and status together."""
        with self.engine.begin() as db:
            source = (
                db.execute(
                    select(sources)
                    .where(
                        sources.c.project_id == project_id, sources.c.id == source_id
                    )
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if source is None:
                raise ApplicationError("Wiki source not found", 404, "not_found")
            now = datetime.now(UTC).isoformat()
            existing = None
            if source["page_id"]:
                existing = (
                    db.execute(
                        select(pages).where(
                            pages.c.project_id == project_id,
                            pages.c.id == source["page_id"],
                        )
                    )
                    .mappings()
                    .first()
                )
            values = make_page(
                {**dict(source), "page_path": existing["path"] if existing else None}
            )
            if existing:
                page_id = existing["id"]
                db.execute(
                    update(pages)
                    .where(pages.c.id == page_id)
                    .values(**values, revision=pages.c.revision + 1, updated_at=now)
                )
            else:
                page = new_record(project_id=project_id, revision=1, **values)
                page_id = page["id"]
                db.execute(insert(pages), page)
            db.execute(
                update(sources)
                .where(sources.c.id == source_id)
                .values(
                    status="ingested",
                    page_id=page_id,
                    error_message=None,
                    updated_at=now,
                )
            )
        return self.get_page(project_id, page_id)

    def mark_source_failed(self, project_id, source_id):
        with self.engine.begin() as db:
            db.execute(
                update(sources)
                .where(sources.c.project_id == project_id, sources.c.id == source_id)
                .values(
                    status="failed",
                    error_message="Source ingestion failed",
                    updated_at=datetime.now(UTC).isoformat(),
                )
            )

    def add_attachment(self, project_id, page_id, filename, media_type, content):
        self.get_page(project_id, page_id)
        row = new_record(
            project_id=project_id,
            page_id=page_id,
            filename=filename,
            media_type=media_type,
            content=content,
        )
        row.pop("updated_at")
        with self.engine.begin() as db:
            db.execute(insert(attachments), row)
        return {key: value for key, value in row.items() if key != "content"}

    def get_attachment(self, project_id, attachment_id):
        with self.engine.connect() as db:
            row = (
                db.execute(
                    select(attachments).where(
                        attachments.c.project_id == project_id,
                        attachments.c.id == attachment_id,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ApplicationError("Wiki attachment not found", 404, "not_found")
            return dict(row)

    def list_attachments(self, project_id, page_id):
        self.get_page(project_id, page_id)
        with self.engine.connect() as db:
            return [
                {key: value for key, value in dict(row).items() if key != "content"}
                for row in db.execute(
                    select(attachments)
                    .where(
                        attachments.c.project_id == project_id,
                        attachments.c.page_id == page_id,
                    )
                    .order_by(attachments.c.created_at, attachments.c.id)
                ).mappings()
            ]

    def delete_attachment(self, project_id, attachment_id):
        with self.engine.begin() as db:
            if (
                db.execute(
                    delete(attachments).where(
                        attachments.c.project_id == project_id,
                        attachments.c.id == attachment_id,
                    )
                ).rowcount
                != 1
            ):
                raise ApplicationError("Wiki attachment not found", 404, "not_found")

    def export_snapshot(self, project_id):
        with self.engine.connect() as db, db.begin():
            project = (
                db.execute(select(projects).where(projects.c.id == project_id))
                .mappings()
                .first()
            )
            if project is None:
                raise ApplicationError("Wiki project not found", 404, "not_found")

            def rows(table):
                return [
                    dict(row)
                    for row in db.execute(
                        select(table).where(table.c.project_id == project_id)
                    ).mappings()
                ]

            return dict(project), rows(pages), rows(sources), rows(attachments)

    def import_snapshot(self, project_values, page_values, source_values, asset_values):
        """Import as a new project, atomically; never overwrite an existing project."""
        project = new_record(**project_values)
        with self.engine.begin() as db:
            db.execute(insert(projects), project)
            page_ids = {}
            for values in page_values:
                row = new_record(project_id=project["id"], revision=1, **values)
                page_ids[row["path"]] = row["id"]
                db.execute(insert(pages), row)
            for values in source_values:
                values = dict(values)
                page_path = values.pop("page_path")
                status = values.pop("status")
                db.execute(
                    insert(sources),
                    new_record(
                        project_id=project["id"],
                        status=status,
                        page_id=page_ids.get(page_path),
                        error_message="Source ingestion failed"
                        if status == "failed"
                        else None,
                        **values,
                    ),
                )
            for values in asset_values:
                values = dict(values)
                page_id = page_ids[values.pop("page_path")]
                row = new_record(project_id=project["id"], page_id=page_id, **values)
                row.pop("updated_at")
                db.execute(insert(attachments), row)
        return project
