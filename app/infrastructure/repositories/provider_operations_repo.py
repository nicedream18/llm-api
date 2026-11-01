"""Account operations, with account-row locks serializing lifecycle changes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.application.errors import ApplicationError


def stamp() -> str:
    return datetime.now(UTC).isoformat()


def literal_like(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


class ProviderOperationsRepository:
    """Mixin sharing the provider repository's SQLAlchemy engine."""

    engine: Engine

    @staticmethod
    def _lock(db, account_id):
        suffix = " FOR UPDATE" if db.engine.dialect.name == "mysql" else ""
        row = db.execute(text("SELECT * FROM provider_accounts WHERE id=:id" + suffix), {"id": account_id}).mappings().first()
        if row is None:
            raise ApplicationError("Provider account not found", 404, "not_found")
        return row

    @staticmethod
    def _event(db, account_id, action, details):
        db.execute(text("""INSERT INTO provider_account_events (id,account_id,action,details,created_at)
            VALUES (:id,:account,:action,:details,:now)"""), {
            "id": uuid.uuid4().hex, "account": account_id, "action": action,
            "details": json.dumps(details, ensure_ascii=False), "now": stamp(),
        })

    @staticmethod
    def _profile(db, account_id):
        row = db.execute(text("SELECT * FROM provider_account_profiles WHERE account_id=:id"), {"id": account_id}).mappings().first()
        if row:
            return dict(row)
        db.execute(text("""INSERT INTO provider_account_profiles (account_id,enabled,group_name,tags)
            VALUES (:id,1,'','[]')"""), {"id": account_id})
        return {"enabled": 1, "group_name": "", "tags": "[]", "archived_at": None}

    def query_accounts(self, query):
        filters = ["p.archived_at IS NOT NULL" if query.archived else "p.archived_at IS NULL"]
        params = {"limit": query.limit, "offset": query.offset}
        for field in ("provider", "status", "group_name"):
            value = getattr(query, field)
            if value is not None:
                column = "COALESCE(p.group_name,'')" if field == "group_name" else "a." + field
                filters.append(column + "=:" + field)
                params[field] = value
        if query.enabled is not None:
            filters.append("COALESCE(p.enabled,1)=:enabled")
            params["enabled"] = int(query.enabled)
        if query.search:
            filters.append("a.name LIKE :search ESCAPE '!'")
            params["search"] = literal_like(query.search)
        if query.tag:
            filters.append("p.tags LIKE :tag ESCAPE '!'")
            params["tag"] = literal_like(json.dumps(query.tag, ensure_ascii=False))
        sorting = {"priority": "a.priority", "name": "a.name", "provider": "a.provider", "created_at": "a.created_at"}
        direction = "DESC" if query.descending else "ASC"
        source = " FROM provider_accounts a LEFT JOIN provider_account_profiles p ON p.account_id=a.id WHERE " + " AND ".join(filters)
        with self.engine.connect() as db:
            total = db.execute(text("SELECT COUNT(*)" + source), params).scalar()
            items = db.execute(text("""SELECT a.*, COALESCE(p.enabled,1) AS enabled,
                COALESCE(p.group_name,'') AS group_name, COALESCE(p.tags,'[]') AS tags, p.archived_at"""
                + source + f" ORDER BY {sorting[query.sort]} {direction}, a.id ASC LIMIT :limit OFFSET :offset"), params).mappings()
            return {"items": [dict(row) for row in items], "total": int(total or 0), "offset": query.offset, "limit": query.limit}

    def account_profile(self, account_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM provider_account_profiles WHERE account_id=:id"), {"id": account_id}).mappings().first()
            return dict(row) if row else {"enabled": 1, "group_name": "", "tags": "[]", "archived_at": None}

    def operate_account(self, account_id, operation, value=None):
        with self.engine.begin() as db:
            self._lock(db, account_id)
            profile = self._profile(db, account_id)
            if profile["archived_at"] and operation != "restore":
                if operation == "archive":
                    return False
                raise ApplicationError("Provider account is archived", 409, "account_archived")
            fields = {}
            if operation == "archive":
                fields = {"enabled": 0, "archived_at": stamp()}
                self._invalidate_auth(db, account_id)
                db.execute(text("DELETE FROM provider_tokens WHERE account_id=:id"), {"id": account_id})
                db.execute(text("UPDATE provider_accounts SET status='signed_out',updated_at=:now WHERE id=:id"), {"id": account_id, "now": stamp()})
            elif operation == "restore":
                if not profile["archived_at"]:
                    return False
                fields = {"enabled": 0, "archived_at": None}
            elif operation == "enabled":
                fields = {"enabled": int(value)}
            elif operation == "group_name":
                fields = {"group_name": value}
            elif operation == "tags":
                fields = {"tags": json.dumps(value, ensure_ascii=False)}
            else:
                raise ApplicationError("Invalid account operation", 422, "invalid_operation")
            changed = any(profile.get(key) != item for key, item in fields.items())
            if changed:
                setters = ",".join(f"{key}=:{key}" for key in fields)
                db.execute(text(f"UPDATE provider_account_profiles SET {setters} WHERE account_id=:id"), {**fields, "id": account_id})
                db.execute(text("UPDATE provider_accounts SET updated_at=:now WHERE id=:id"), {"id": account_id, "now": stamp()})
                self._event(db, account_id, operation, fields)
            return changed

    def account_events(self, account_id, limit=50, offset=0):
        with self.engine.connect() as db:
            rows = db.execute(text("""SELECT * FROM provider_account_events WHERE account_id=:id
                ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"""), {"id": account_id, "limit": limit, "offset": offset}).mappings()
            return [dict(row) for row in rows]
