"""Log repository for request_logs."""
import logging
from datetime import UTC, datetime

from sqlalchemy import text

from app.domain.entities import LogStatsEntity, RequestLogEntity
from app.infrastructure.database.connection import affected_rows, get_db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()

_ALL_COLUMNS = (
    "id, seq, api_key_id, api_key_name, channel_id, channel_name, model, upstream_model, "
    "mode, protocol_type, is_stream AS stream, is_retry, status_code, prompt_tokens, completion_tokens, "
    "total_tokens, duration_ms, request_id, endpoint, attempt_count, final_attempt, stream_status, usage_source, client_disconnect, truncated, risk_level, risk_score, risk_summary, security_action, "
    "sanitized, blocked_reason, client_ip, error_message, request_body, response_choices, "
    "trace_id, created_at"
)


class LogRepository:

    def insert_attempt(self, request_id: str, attempt) -> None:
        with get_db() as db:
            db.execute(text("""INSERT INTO gateway_attempts
                (id, request_id, attempt_no, channel_id, channel_name, status_code,
                 error_type, error_message, duration_ms, succeeded, created_at)
                VALUES (:id, :request_id, :attempt_no, :channel_id, :channel_name,
                        :status_code, :error_type, :error_message, :duration_ms,
                        :succeeded, :created_at)"""), {
                "id": __import__("uuid").uuid4().hex,
                "request_id": request_id,
                "attempt_no": attempt.attempt_no,
                "channel_id": attempt.channel_id,
                "channel_name": attempt.channel_name,
                "status_code": attempt.status_code,
                "error_type": attempt.error_type,
                "error_message": attempt.error_message,
                "duration_ms": attempt.duration_ms,
                "succeeded": 1 if attempt.succeeded else 0,
                "created_at": _now(),
            })

    def insert_log(self, log: RequestLogEntity):
        with get_db() as db:
            db.execute(text(
                "INSERT INTO request_logs (id, api_key_id, api_key_name, channel_id, channel_name, "
                "model, upstream_model, mode, protocol_type, is_stream, is_retry, status_code, request_id, endpoint, attempt_count, final_attempt, stream_status, usage_source, client_disconnect, truncated, "
                "prompt_tokens, completion_tokens, total_tokens, duration_ms, risk_level, risk_score, "
                "risk_summary, security_action, sanitized, blocked_reason, client_ip, error_message, "
                "request_body, response_choices, trace_id, created_at) "
                "VALUES (:id, :api_key_id, :api_key_name, :channel_id, :channel_name, "
                ":model, :upstream_model, :mode, :protocol_type, :stream, :is_retry, :status_code, :request_id, :endpoint, :attempt_count, :final_attempt, :stream_status, :usage_source, :client_disconnect, :truncated, "
                ":prompt_tokens, :completion_tokens, :total_tokens, :duration_ms, :risk_level, :risk_score, "
                ":risk_summary, :security_action, :sanitized, :blocked_reason, :client_ip, :error_message, "
                ":request_body, :response_choices, :trace_id, :created_at)"
            ), {
                "id": log.id, "api_key_id": log.api_key_id, "api_key_name": log.api_key_name,
                "channel_id": log.channel_id, "channel_name": log.channel_name,
                "model": log.model, "upstream_model": log.upstream_model,
                "mode": log.mode, "protocol_type": log.protocol_type,
                "stream": 1 if log.stream else 0, "is_retry": 1 if log.retry else 0,
                "status_code": log.status_code, "request_id": getattr(log, "request_id", None), "endpoint": getattr(log, "endpoint", None), "attempt_count": getattr(log, "attempt_count", 1), "final_attempt": getattr(log, "final_attempt", 1), "stream_status": getattr(log, "stream_status", None), "usage_source": getattr(log, "usage_source", None), "client_disconnect": 1 if getattr(log, "client_disconnect", False) else 0, "truncated": 1 if getattr(log, "truncated", False) else 0, "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens, "total_tokens": log.total_tokens,
                "duration_ms": log.duration_ms, "risk_level": log.risk_level,
                "risk_score": log.risk_score, "risk_summary": log.risk_summary,
                "security_action": log.security_action, "sanitized": 1 if log.sanitized else 0,
                "blocked_reason": log.blocked_reason, "client_ip": log.client_ip,
                "error_message": log.error_message, "request_body": log.request_body,
                "response_choices": log.response_choices, "trace_id": log.trace_id,
                "created_at": log.created_at or _now(),
            })

    def get_log_by_id(self, log_id: str) -> RequestLogEntity | None:
        with get_db() as db:
            row = db.execute(text(f"SELECT {_ALL_COLUMNS} FROM request_logs WHERE id = :id"), {"id": log_id}).mappings().first()
            return self._to_entity(row) if row else None

    def query_logs(self, offset, limit, api_key_id=None, channel_id=None, model=None,
                   risk_level=None, start_time=None, end_time=None) -> list[RequestLogEntity]:
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
                    model=None, date_from=None, date_to=None, trace_id=None) -> list[RequestLogEntity]:
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
            return affected_rows(result) > 0

    def delete_all_logs(self) -> bool:
        with get_db() as db:
            db.execute(text("DELETE FROM request_logs"))
            return True

    def model_stats(self):
        with get_db() as db:
            rows = db.execute(text("""SELECT model, COUNT(*) AS requests,
                COALESCE(SUM(total_tokens),0) AS total_tokens,
                COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END),0) AS errors
                FROM request_logs GROUP BY model ORDER BY requests DESC""")).mappings()
            return [dict(row) for row in rows]

    def token_trend(self, days: int = 30):
        with get_db() as db:
            rows = db.execute(text("""SELECT SUBSTRING(created_at,1,10) AS day,
                COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                COALESCE(SUM(total_tokens),0) AS total_tokens
                FROM request_logs GROUP BY SUBSTRING(created_at,1,10)
                ORDER BY day DESC LIMIT :days"""), {"days": min(max(int(days), 1), 366)}).mappings()
            return [dict(row) for row in rows]

    def route_flow(self):
        with get_db() as db:
            rows = db.execute(text("""SELECT channel_id, channel_name, endpoint,
                COUNT(*) AS requests, COALESCE(SUM(total_tokens),0) AS total_tokens
                FROM request_logs GROUP BY channel_id, channel_name, endpoint
                ORDER BY requests DESC""")).mappings()
            return [dict(row) for row in rows]

    def filter_options(self):
        with get_db() as db:
            models = [row[0] for row in db.execute(text("SELECT DISTINCT model FROM request_logs WHERE model IS NOT NULL ORDER BY model"))]
            channels = [dict(row) for row in db.execute(text("SELECT DISTINCT channel_id, channel_name FROM request_logs WHERE channel_id IS NOT NULL ORDER BY channel_name")).mappings()]
            risks = [row[0] for row in db.execute(text("SELECT DISTINCT risk_level FROM request_logs WHERE risk_level IS NOT NULL ORDER BY risk_level"))]
            return {"models": models, "channels": channels, "risk_levels": risks}

    def attempts(self, request_id):
        with get_db() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM gateway_attempts WHERE request_id=:request_id ORDER BY attempt_no"), {"request_id": request_id}).mappings()]

    def delete_before(self, cutoff):
        with get_db() as db:
            return affected_rows(db.execute(text("DELETE FROM request_logs WHERE created_at < :cutoff"), {"cutoff": cutoff}))

    def delete_by_channel(self, channel_id):
        with get_db() as db:
            return affected_rows(db.execute(text("DELETE FROM request_logs WHERE channel_id=:channel_id"), {"channel_id": channel_id}))

    def clear_stats(self):
        with get_db() as db:
            db.execute(text("UPDATE request_logs SET prompt_tokens=0, completion_tokens=0, total_tokens=0"))

    def _to_entity(self, row) -> RequestLogEntity:
        return RequestLogEntity(
            id=row["id"], seq=row["seq"], request_id=row.get("request_id"), endpoint=row.get("endpoint"), attempt_count=int(row.get("attempt_count") or 1), final_attempt=int(row.get("final_attempt") or 1), stream_status=row.get("stream_status"), usage_source=row.get("usage_source"), client_disconnect=bool(row.get("client_disconnect")), truncated=bool(row.get("truncated")), api_key_id=row["api_key_id"], api_key_name=row["api_key_name"],
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
