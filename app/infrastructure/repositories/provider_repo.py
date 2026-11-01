"""Persistence for provider accounts and encrypted tokens."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


def _now():
    return datetime.now(UTC).isoformat()


class ProviderRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def list_accounts(self):
        with self.engine.connect() as db:
            rows = []
            for row in db.execute(text("SELECT * FROM provider_accounts ORDER BY priority DESC, created_at")).mappings():
                item = dict(row)
                item.setdefault("failure_count", 0)
                item.setdefault("cooldown_until", None)
                rows.append(item)
            return rows

    def get_account(self, account_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM provider_accounts WHERE id=:id"), {"id": account_id}).mappings().first()
            return dict(row) if row else None

    def create_account(self, values):
        row = {"id": str(uuid.uuid4()), "status": "pending", "created_at": _now(), "updated_at": _now(), **values}
        row["client_config"] = json.dumps(row.get("client_config") or {}, ensure_ascii=False)
        row["model_mapping"] = json.dumps(row.get("model_mapping") or {}, ensure_ascii=False)
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO provider_accounts
                (id,provider,name,status,client_config,model_mapping,priority,created_at,updated_at)
                VALUES (:id,:provider,:name,:status,:client_config,:model_mapping,:priority,:created_at,:updated_at)"""), row)
        return self.get_account(row["id"])

    def update_account(self, account_id, values):
        values = {**values, "id": account_id, "updated_at": _now()}
        for key in ("client_config", "model_mapping"):
            if key in values:
                values[key] = json.dumps(values[key] or {}, ensure_ascii=False)
        fields = ", ".join(f"{key}=:{key}" for key in values if key != "id")
        with self.engine.begin() as db:
            db.execute(text(f"UPDATE provider_accounts SET {fields} WHERE id=:id"), values)
        return self.get_account(account_id)

    def delete_account(self, account_id):
        with self.engine.begin() as db:
            dialect = getattr(getattr(db, "bind", None), "dialect", None)
            lock_suffix = " FOR UPDATE" if getattr(dialect, "name", None) == "mysql" else ""
            exists = db.execute(
                text("SELECT id FROM provider_accounts WHERE id=:id" + lock_suffix),
                {"id": account_id},
            ).first()
            if not exists:
                return False
            db.execute(text("DELETE FROM provider_tokens WHERE account_id=:id"), {"id": account_id})
            return db.execute(
                text("DELETE FROM provider_accounts WHERE id=:id"),
                {"id": account_id},
            ).rowcount > 0

    def save_token(self, account_id, values):
        row = {"id": str(uuid.uuid4()), "account_id": account_id, "created_at": _now(), "updated_at": _now(), **values}
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM provider_tokens WHERE account_id=:account_id"), {"account_id": account_id})
            db.execute(text("""INSERT INTO provider_tokens
                (id,account_id,access_token,refresh_token,expires_at,created_at,updated_at)
                VALUES (:id,:account_id,:access_token,:refresh_token,:expires_at,:created_at,:updated_at)"""), row)
            db.execute(text("UPDATE provider_accounts SET status='active', updated_at=:updated_at WHERE id=:id"), {"id": account_id, "updated_at": row["updated_at"]})

    def get_token(self, account_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM provider_tokens WHERE account_id=:id ORDER BY created_at DESC"), {"id": account_id}).mappings().first()
            return dict(row) if row else None

    def delete_token(self, account_id):
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM provider_tokens WHERE account_id=:id"), {"id": account_id})
            db.execute(text("UPDATE provider_accounts SET status='signed_out', updated_at=:updated_at WHERE id=:id"), {"id": account_id, "updated_at": _now()})

    def record_failure(self, account_id, cooldown_until):
        with self.engine.begin() as db:
            db.execute(text("""UPDATE provider_accounts
                SET failure_count=COALESCE(failure_count, 0) + 1,
                    cooldown_until=:cooldown_until, updated_at=:updated_at
                WHERE id=:id"""), {"id": account_id, "cooldown_until": cooldown_until, "updated_at": _now()})
        return self.get_account(account_id)

    def clear_failures(self, account_id):
        with self.engine.begin() as db:
            db.execute(text("""UPDATE provider_accounts SET failure_count=0,
                cooldown_until=NULL, updated_at=:updated_at WHERE id=:id"""), {"id": account_id, "updated_at": _now()})
        return self.get_account(account_id)
