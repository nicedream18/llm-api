"""Log repository for request_logs."""
import logging
from typing import List, Optional
from sqlalchemy import text

from app.infrastructure.database.connection import get_db
from app.domain.entities import RequestLogEntity, LogStatsEntity

logger = logging.getLogger(__name__)

_ALL_COLUMNS = (
    "id, seq, api_key_id, api_key_name, channel_id, channel_name, model, upstream_model, "
    "mode, protocol_type, stream, is_retry, status_code, prompt_tokens, completion_tokens, "
    "total_tokens, duration_ms, risk_level, risk_score, risk_summary, security_action, "
    "sanitized, blocked_reason, client_ip, error_message, request_body, response_choices, "
    "trace_id, created_at"
)


class LogRepository:

    def insert_log(self, log: RequestLogEntity):
        with get_db() as db:
            db.execute(text(
                "INSERT INTO request_logs (id, api_key_id, api_key_name, channel_id, channel_name, "
                "model, upstream_model, mode, protocol_type, stream, is_retry, status_code, "
                "prompt_tokens, completion_tokens, total_tokens, duration_ms, risk_level, risk_score, "
                "risk_summary, security_action, sanitized, blocked_reason, client_ip, error_message, "
                "request_body, response_choices, trace_id, created_at) "
                "VALUES (:id, :api_key_id, :api_key_name, :channel_id, :channel_name, "
                ":model, :upstream_model, :mode, :protocol_type, :stream, :is_retry, :status_code, "
                ":prompt_tokens, :completion_tokens, :total_tokens, :duration_ms, :risk_level, :risk_score, "
                ":risk_summary, :security_action, :sanitized, :blocked_reason, :client_ip, :error_message, "
                ":request_body, :response_choices, :trace_id, :created_at)"
            ), {
                "id": log.id, "api_key_id": log.api_key_id, "api_key_name": log.api_key_name,
                "channel_id": log.channel_id, "channel_name": log.channel_name,
                "model": log.model, "upstream_model": log.upstream_model,
                "mode": log.mode, "protocol_type": log.protocol_type,
                "stream": 1 if log.stream else 0, "is_retry": 1 if log.retry else 0,
                "status_code": log.status_code, "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens, "total_tokens": log.total_tokens,
                "duration_ms": log.duration_ms, "risk_level": log.risk_level,
                "risk_score": log.risk_score, "risk_summary": log.risk_summary,
                "security_action": log.security_action, "sanitized": 1 if log.sanitized else 0,
                "blocked_reason": log.blocked_reason, "client_ip": log.client_ip,
                "error_message": log.error_message, "request_body": log.request_body,
                "response_choices": log.response_choices, "trace_id": log.trace_id,
                "created_at": log.created_at,
            })

    def get_log_by_id(self, log_id: str) -> Optional[RequestLogEntity]:
        with get_db() as db:
            row = db.execute(text(f"SELECT {_ALL_COLUMNS} FROM request_logs WHERE id = :id"), {"id": log_id}).mappings().first()
            return self._to_entity(row) if row else None

    def query_logs(self, offset, limit, api_key_id=None, channel_id=None, model=None,
                   risk_level=None, start_time=None, end_time=None) -> List[RequestLogEntity]:
        sql = f"SELECT {_ALL_COLUMNS} FROM request_logs WHERE 1=1"
        params = {"offset": offset, "limit": limit}
        if api_key_id: sql += " AND api_key_id = :api_key_id"; params["api_key_id"] = api_key_id
        if channel_id: sql += " AND channel_id = :channel_id"; params["channel_id"] = channel_id
        if model: sql += " AND model = :model"; params["model"] = model
        if risk_level: sql += " AND risk_level = :risk_level"; params["risk_level"] = risk_level
        if start_time: sql += " AND created_at >= :start_time"; params["start_time"] = start_time
        if end_time: sql += " AND created_at <= :end_time"; params["end_time"] = end_time
        sql += " ORDER BY created_at DESC LIMIT :offset, :limit"
        with get_db() as db:
            rows = db.execute(text(sql), params).mappings().all()
            return [self._to_entity(r) for r in rows]

    def search_logs(self, offset, limit, keyword=None, api_key_name=None, channel_name=None,
                    model=None, date_from=None, date_to=None, trace_id=None) -> List[RequestLogEntity]:
        sql = f"SELECT {_ALL_COLUMNS} FROM request_logs WHERE 1=1"
        params = {"offset": offset, "limit": limit}
        if keyword: sql += " AND (error_message LIKE :kw OR model LIKE :kw)"; params["kw"] = f"%{keyword}%"
        if api_key_name: sql += " AND api_key_name LIKE :akn"; params["akn"] = f"%{api_key_name}%"
        if channel_name: sql += " AND channel_name LIKE :cn"; params["cn"] = f"%{channel_name}%"
        if model: sql += " AND model = :model"; params["model"] = model
        if date_from: sql += " AND created_at >= :df"; params["df"] = date_from
        if date_to: sql += " AND created_at <= :dt"; params["dt"] = date_to
        if trace_id: sql += " AND id = :tid"; params["tid"] = trace_id
        sql += " ORDER BY created_at DESC LIMIT :offset, :limit"
        with get_db() as db:
            rows = db.execute(text(sql), params).mappings().all()
            return [self._to_entity(r) for r in rows]

    def get_dashboard_stats(self) -> LogStatsEntity:
        with get_db() as db:
            row = db.execute(text(
                "SELECT (SELECT COUNT(*) FROM request_logs) AS total_requests, "
                "(SELECT COALESCE(SUM(total_tokens), 0) FROM request_logs) AS total_tokens, "
                "(SELECT COUNT(*) FROM request_logs WHERE status_code >= 400) AS total_errors, "
                "(SELECT COALESCE(AVG(duration_ms), 0) FROM request_logs) AS avg_duration_ms, "
                "(SELECT COUNT(*) FROM channels WHERE status = 1) AS active_channels, "
                "(SELECT COUNT(*) FROM api_keys WHERE status = 1) AS active_api_keys"
            )).mappings().first()
            if not row:
                return LogStatsEntity()
            return LogStatsEntity(
                total_requests=int(row["total_requests"] or 0),
                total_tokens=int(row["total_tokens"] or 0),
                total_errors=int(row["total_errors"] or 0),
                avg_duration_ms=float(row["avg_duration_ms"] or 0),
                active_channels=int(row["active_channels"] or 0),
                active_api_keys=int(row["active_api_keys"] or 0),
            )

    def delete_log(self, log_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM request_logs WHERE id = :id"), {"id": log_id})
            return result.rowcount > 0

    def delete_all_logs(self) -> bool:
        with get_db() as db:
            db.execute(text("DELETE FROM request_logs"))
            return True

    def _to_entity(self, row) -> RequestLogEntity:
        return RequestLogEntity(
            id=row["id"], seq=row["seq"], api_key_id=row["api_key_id"], api_key_name=row["api_key_name"],
            channel_id=row["channel_id"], channel_name=row["channel_name"], model=row["model"],
            upstream_model=row["upstream_model"], mode=row["mode"], protocol_type=row["protocol_type"],
            stream=bool(row["stream"]), retry=bool(row["is_retry"]), status_code=row["status_code"],
            prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"], duration_ms=row["duration_ms"],
            risk_level=row["risk_level"], risk_score=row["risk_score"], risk_summary=row["risk_summary"],
            security_action=row["security_action"], sanitized=bool(row["sanitized"]),
            blocked_reason=row["blocked_reason"], client_ip=row["client_ip"],
            error_message=row["error_message"], request_body=row["request_body"],
            response_choices=row["response_choices"], trace_id=row["trace_id"],
            created_at=row["created_at"],
        )
