"""Database-backed access grants. Wildcards are explicit administrator grants."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.application.errors import ApplicationError
from app.infrastructure.database.connection import engine as default_engine


class AccessRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def list_grants(self):
        with self.engine.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    text("SELECT * FROM access_grants ORDER BY created_at, id")
                ).mappings()
            ]

    def create(self, values):
        row = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            **values,
        }
        try:
            with self.engine.begin() as db:
                db.execute(
                    text("""INSERT INTO access_grants
                    (id,principal_type,principal_id,resource_type,resource_id,action,created_at)
                    VALUES (:id,:principal_type,:principal_id,:resource_type,:resource_id,:action,:created_at)"""),
                    row,
                )
        except IntegrityError as exc:
            raise ApplicationError(
                "Grant already exists", 409, "grant_conflict"
            ) from exc
        return row

    def delete(self, grant_id):
        with self.engine.begin() as db:
            if (
                db.execute(
                    text("DELETE FROM access_grants WHERE id=:id"), {"id": grant_id}
                ).rowcount
                != 1
            ):
                raise ApplicationError("Grant not found", 404, "not_found")

    def allowed_resources(self, principal_type, principal_id, resource_type, action):
        with self.engine.connect() as db:
            rows = db.execute(
                text("""SELECT resource_id FROM access_grants
                WHERE principal_type=:principal_type AND principal_id=:principal_id
                AND resource_type=:resource_type AND action=:action"""),
                {
                    "principal_type": principal_type,
                    "principal_id": principal_id,
                    "resource_type": resource_type,
                    "action": action,
                },
            ).scalars()
            return frozenset(rows)
