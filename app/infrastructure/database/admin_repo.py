"""Persistence for the administrator account and audit events."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import affected_rows, get_db


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AdminRepository:
    def get_user(self, username: str):
        with get_db() as db:
            return db.execute(text("SELECT username, password_hash, status FROM admin_users WHERE username=:username LIMIT 1"), {"username": username}).mappings().first()

    def upsert_user(self, username: str, password_hash: str) -> None:
        with get_db() as db:
            db.execute(text("""INSERT INTO admin_users (id, username, password_hash, status, created_at, updated_at)
                VALUES (:id, :username, :password_hash, 1, :now, :now)
                ON DUPLICATE KEY UPDATE password_hash=:password_hash, status=1, updated_at=:now"""),
                       {"id": str(uuid.uuid4()), "username": username, "password_hash": password_hash, "now": _now()})

    def change_password(self, username: str, password_hash: str) -> bool:
        with get_db() as db:
            result = db.execute(text("UPDATE admin_users SET password_hash=:password_hash, updated_at=:now WHERE username=:username AND status=1"),
                                {"username": username, "password_hash": password_hash, "now": _now()})
            return affected_rows(result) > 0

    def write_audit(self, username: str | None, action: str, request_id: str | None, client_ip: str | None, success: bool = True) -> None:
        with get_db() as db:
            db.execute(text("""INSERT INTO admin_audit_logs (id, username, action, request_id, client_ip, success, created_at)
                VALUES (:id, :username, :action, :request_id, :client_ip, :success, :created_at)"""),
                       {"id": str(uuid.uuid4()), "username": username, "action": action, "request_id": request_id,
                        "client_ip": client_ip, "success": 1 if success else 0, "created_at": _now()})
