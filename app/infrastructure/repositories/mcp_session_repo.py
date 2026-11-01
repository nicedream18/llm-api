"""Persistent MCP session ownership and bounded notification history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.isoformat()


def _parse_stamp(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return _now()
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@dataclass(frozen=True)
class ReplayResult:
    """A replay outcome with enough information for protocol error handling.

    The old ``replay`` method intentionally remains a list-returning compatibility
    wrapper.  Streamable HTTP needs to distinguish a stale cursor from an expired
    session, though, so callers that expose the protocol use this richer result.
    """

    status: str
    events: list[dict]
    first_event_id: int | None = None
    last_event_id: int = 0


class McpSessionRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def create(self, session_id: str, owner: tuple[str | None, str | None], ttl_seconds: int) -> None:
        now = _now()
        expires = now + timedelta(seconds=max(1, int(ttl_seconds)))
        with self.engine.begin() as db:
            db.execute(
                text("""INSERT INTO mcp_sessions
                    (id, principal_type, principal_id, expires_at, created_at, updated_at)
                    VALUES (:id, :principal_type, :principal_id, :expires_at, :created_at, :updated_at)"""),
                {
                    "id": session_id,
                    "principal_type": owner[0],
                    "principal_id": owner[1],
                    "expires_at": _stamp(expires),
                    "created_at": _stamp(now),
                    "updated_at": _stamp(now),
                },
            )

    def validate(self, session_id: str, owner: tuple[str | None, str | None], ttl_seconds: int) -> bool:
        now = _now()
        with self.engine.begin() as db:
            row = db.execute(
                text("SELECT principal_type, principal_id, expires_at FROM mcp_sessions WHERE id=:id"),
                {"id": session_id},
            ).mappings().first()
            if not row:
                return False
            expires_at = _parse_stamp(row["expires_at"])
            if expires_at <= now or (row["principal_type"], row["principal_id"]) != owner:
                if expires_at <= now:
                    db.execute(text("DELETE FROM mcp_sessions WHERE id=:id"), {"id": session_id})
                return False
            db.execute(
                text("UPDATE mcp_sessions SET expires_at=:expires_at, updated_at=:updated_at WHERE id=:id"),
                {"id": session_id, "expires_at": _stamp(now + timedelta(seconds=max(1, int(ttl_seconds)))), "updated_at": _stamp(now)},
            )
            return True

    def delete(self, session_id: str) -> bool:
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM mcp_sessions WHERE id=:id"), {"id": session_id}).rowcount > 0

    def cleanup_expired(self) -> int:
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM mcp_sessions WHERE expires_at <= :now"), {"now": _stamp(_now())}).rowcount

    def append_event(self, session_id: str, payload: dict, max_events: int = 64) -> int | None:
        now = _stamp(_now())
        with self.engine.begin() as db:
            dialect = getattr(getattr(db, "engine", None), "dialect", None)
            lock_suffix = " FOR UPDATE" if getattr(dialect, "name", None) == "mysql" else ""
            if not db.execute(text("SELECT id FROM mcp_sessions WHERE id=:id" + lock_suffix), {"id": session_id}).first():
                return None
            last = db.execute(
                text("SELECT COALESCE(MAX(event_id), 0) FROM mcp_session_events WHERE session_id=:id" + lock_suffix),
                {"id": session_id},
            ).scalar_one()
            event_id = int(last or 0) + 1
            db.execute(
                text("""INSERT INTO mcp_session_events (session_id, event_id, payload, created_at)
                    VALUES (:session_id, :event_id, :payload, :created_at)"""),
                {"session_id": session_id, "event_id": event_id, "payload": json.dumps(payload, ensure_ascii=False, separators=(",", ":")), "created_at": now},
            )
            keep_from = max(1, event_id - max(1, int(max_events)) + 1)
            db.execute(
                text("DELETE FROM mcp_session_events WHERE session_id=:session_id AND event_id < :keep_from"),
                {"session_id": session_id, "keep_from": keep_from},
            )
            db.execute(
                text("UPDATE mcp_sessions SET updated_at=:updated_at WHERE id=:id"),
                {"id": session_id, "updated_at": now},
            )
            return event_id

    def replay_checked(self, session_id: str, owner: tuple[str | None, str | None], after_event_id: int = 0) -> ReplayResult:
        now_dt = _now()
        with self.engine.connect() as db:
            session = db.execute(
                text("SELECT principal_type, principal_id, expires_at FROM mcp_sessions WHERE id=:id"),
                {"id": session_id},
            ).mappings().first()
            if not session:
                return ReplayResult("not_found", [])
            if (session["principal_type"], session["principal_id"]) != owner:
                return ReplayResult("owner_mismatch", [])
            expires_at = _parse_stamp(session["expires_at"])
            if expires_at <= now_dt:
                return ReplayResult("expired", [])
            cursor = max(0, int(after_event_id))
            bounds = db.execute(
                text("SELECT MIN(event_id), MAX(event_id) FROM mcp_session_events WHERE session_id=:id"),
                {"id": session_id},
            ).first()
            first_event_id = int(bounds[0]) if bounds and bounds[0] is not None else None
            last_event_id = int(bounds[1] or 0) if bounds else 0
            if first_event_id is not None and cursor and cursor < first_event_id - 1:
                return ReplayResult("gap", [], first_event_id, last_event_id)
            rows = db.execute(
                text("SELECT event_id, payload, created_at FROM mcp_session_events WHERE session_id=:id AND event_id > :after ORDER BY event_id"),
                {"id": session_id, "after": cursor},
            ).mappings()
            result = []
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                result.append({"event_id": int(row["event_id"]), "payload": payload, "created_at": row["created_at"]})
            return ReplayResult("ok", result, first_event_id, last_event_id)

    def replay(self, session_id: str, owner: tuple[str | None, str | None], after_event_id: int = 0) -> list[dict]:
        """Return replayable events, preserving the pre-persistence API."""
        outcome = self.replay_checked(session_id, owner, after_event_id)
        return outcome.events if outcome.status == "ok" else []
