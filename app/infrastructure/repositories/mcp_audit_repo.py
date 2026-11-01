"""Persistent audit records for MCP tool calls."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


class McpAuditRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def record(
        self,
        *,
        request_id: str | None,
        principal_type: str | None,
        principal_id: str | None,
        tool_name: str,
        success: bool,
        error_type: str | None,
        duration_ms: int,
    ) -> None:
        with self.engine.begin() as db:
            db.execute(
                text("""INSERT INTO mcp_audit_logs
                (id, request_id, principal_type, principal_id, tool_name,
                 success, error_type, duration_ms, created_at)
                VALUES (:id, :request_id, :principal_type, :principal_id,
                        :tool_name, :success, :error_type, :duration_ms, :created_at)"""),
                {
                    "id": str(uuid.uuid4()),
                    "request_id": request_id,
                    "principal_type": principal_type,
                    "principal_id": principal_id,
                    "tool_name": tool_name,
                    "success": 1 if success else 0,
                    "error_type": error_type,
                    "duration_ms": max(0, int(duration_ms)),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )

    def list(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(
                text("""SELECT id, request_id, principal_type, principal_id,
                    tool_name, success, error_type, duration_ms, created_at
                    FROM mcp_audit_logs ORDER BY created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset"""),
                {"limit": min(max(int(limit), 1), 500), "offset": max(int(offset), 0)},
            ).mappings()
            return [dict(row) for row in rows]
