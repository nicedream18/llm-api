"""Atomic API key quota reservation and settlement."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import get_db


def _now() -> str:
    return datetime.now(UTC).isoformat()


class QuotaRepository:
    def reserve(self, api_key_id: str, request_id: str, estimated_tokens: int) -> str | None:
        estimated_tokens = max(0, int(estimated_tokens))
        reservation_id = uuid.uuid4().hex
        with get_db() as db:
            existing = db.execute(text("SELECT id, status FROM api_key_quota_ledger WHERE request_id=:request_id LIMIT 1"),
                                  {"request_id": request_id}).first()
            if existing:
                return str(existing[0]) if existing[1] == "reserved" else None
            result = db.execute(text("""UPDATE api_keys SET quota_used=quota_used+:tokens, updated_at=:now
                WHERE id=:id AND status=1 AND (quota_limit=0 OR quota_used+:tokens <= quota_limit)"""),
                {"id": api_key_id, "tokens": estimated_tokens, "now": _now()})
            if result.rowcount != 1:
                return None
            db.execute(text("""INSERT INTO api_key_quota_ledger
                (id, api_key_id, request_id, reserved_tokens, actual_tokens, released_tokens, status, created_at)
                VALUES (:id, :api_key_id, :request_id, :reserved, 0, 0, 'reserved', :created_at)"""),
                {"id": reservation_id, "api_key_id": api_key_id, "request_id": request_id,
                 "reserved": estimated_tokens, "created_at": _now()})
        return reservation_id

    def settle(self, reservation_id: str, actual_tokens: int) -> bool:
        actual_tokens = max(0, int(actual_tokens))
        with get_db() as db:
            row = db.execute(text("SELECT * FROM api_key_quota_ledger WHERE id=:id FOR UPDATE"), {"id": reservation_id}).mappings().first()
            if not row or row["status"] != "reserved":
                return False
            reserved = int(row["reserved_tokens"] or 0)
            delta = actual_tokens - reserved
            if delta > 0:
                result = db.execute(text("""UPDATE api_keys SET quota_used=quota_used+:delta, updated_at=:now
                    WHERE id=:id AND (quota_limit=0 OR quota_used+:delta <= quota_limit)"""),
                    {"id": row["api_key_id"], "delta": delta, "now": _now()})
                if result.rowcount != 1:
                    actual_tokens = reserved
                    delta = 0
            elif delta < 0:
                db.execute(text("UPDATE api_keys SET quota_used=GREATEST(0, quota_used+:delta), updated_at=:now WHERE id=:id"),
                           {"id": row["api_key_id"], "delta": delta, "now": _now()})
            db.execute(text("""UPDATE api_key_quota_ledger SET actual_tokens=:actual,
                released_tokens=:released, status='settled', settled_at=:now WHERE id=:id"""),
                       {"id": reservation_id, "actual": actual_tokens, "released": max(0, reserved - actual_tokens), "now": _now()})
            return True

    def release(self, reservation_id: str) -> bool:
        with get_db() as db:
            row = db.execute(text("SELECT * FROM api_key_quota_ledger WHERE id=:id FOR UPDATE"), {"id": reservation_id}).mappings().first()
            if not row or row["status"] != "reserved":
                return False
            reserved = int(row["reserved_tokens"] or 0)
            db.execute(text("UPDATE api_keys SET quota_used=GREATEST(0, quota_used-:tokens), updated_at=:now WHERE id=:id"),
                       {"id": row["api_key_id"], "tokens": reserved, "now": _now()})
            db.execute(text("""UPDATE api_key_quota_ledger SET released_tokens=:released,
                status='released', settled_at=:now WHERE id=:id"""),
                       {"id": reservation_id, "released": reserved, "now": _now()})
            return True
