"""Channel and ApiKey repository."""
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import text

from app.infrastructure.database.connection import get_db
from app.domain.entities import ChannelEntity, ApiKeyEntity, ChannelStatsEntity, ApiKeyStatsEntity

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChannelRepository:

    def get_all_channels(self) -> List[ChannelEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at "
                "FROM channels ORDER BY priority DESC, created_at DESC"
            )).mappings().all()
            return [self._to_entity(r) for r in rows]

    def get_channel(self, channel_id: str) -> Optional[ChannelEntity]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at "
                "FROM channels WHERE id = :id"
            ), {"id": channel_id}).mappings().first()
            return self._to_entity(row) if row else None

    def get_enabled_channels(self) -> List[ChannelEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at "
                "FROM channels WHERE status = 1 ORDER BY priority DESC, weight DESC"
            )).mappings().all()
            return [self._to_entity(r) for r in rows]

    def create_channel(self, entity: ChannelEntity) -> ChannelEntity:
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO channels (id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at) "
                "VALUES (:id, :name, :type, :base_url, :api_key, :models, :status, :priority, :weight, "
                ":config, :model_mapping, :last_test_at, :last_test_ok, :created_at, :updated_at)"
            ), self._to_params(entity))
        return entity

    def update_channel(self, entity: ChannelEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET name=:name, type=:type, base_url=:base_url, api_key=:api_key, "
                "models=:models, status=:status, priority=:priority, weight=:weight, "
                "config=:config, model_mapping=:model_mapping, updated_at=:updated_at WHERE id=:id"
            ), self._to_params(entity))
            return result.rowcount > 0

    def delete_channel(self, channel_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM channels WHERE id = :id"), {"id": channel_id})
            return result.rowcount > 0

    def toggle_channel_status(self, channel_id: str, status: int) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET status=:status, updated_at=NOW() WHERE id=:id"
            ), {"id": channel_id, "status": status})
            return result.rowcount > 0

    def update_test_result(self, channel_id: str, ok: bool) -> bool:
        now = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET last_test_at=:t, last_test_ok=:ok, updated_at=:t WHERE id=:id"
            ), {"id": channel_id, "t": now, "ok": 1 if ok else 0})
            return result.rowcount > 0

    def get_channel_stats(self) -> List[ChannelStatsEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT c.id AS channel_id, c.name AS channel_name, COUNT(rl.id) AS total_calls, "
                "SUM(CASE WHEN rl.status_code < 400 THEN 1 ELSE 0 END) AS success_calls, "
                "SUM(CASE WHEN rl.status_code >= 400 THEN 1 ELSE 0 END) AS failed_calls, "
                "COALESCE(SUM(rl.total_tokens), 0) AS total_tokens, "
                "COALESCE(AVG(rl.duration_ms), 0) AS avg_duration_ms "
                "FROM channels c LEFT JOIN request_logs rl ON rl.channel_id = c.id "
                "GROUP BY c.id, c.name ORDER BY total_calls DESC"
            )).mappings().all()
            return [ChannelStatsEntity(
                channel_id=r["channel_id"], channel_name=r["channel_name"],
                total_calls=int(r["total_calls"] or 0), success_calls=int(r["success_calls"] or 0),
                failed_calls=int(r["failed_calls"] or 0), total_tokens=int(r["total_tokens"] or 0),
                avg_duration_ms=float(r["avg_duration_ms"] or 0)
            ) for r in rows]

    def get_api_key_stats(self) -> List[ApiKeyStatsEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT ak.id AS api_key_id, ak.name AS api_key_name, COUNT(rl.id) AS total_calls, "
                "SUM(CASE WHEN rl.status_code < 400 THEN 1 ELSE 0 END) AS success_calls, "
                "SUM(CASE WHEN rl.status_code >= 400 THEN 1 ELSE 0 END) AS failed_calls, "
                "COALESCE(SUM(rl.total_tokens), 0) AS total_tokens, "
                "COALESCE(AVG(rl.duration_ms), 0) AS avg_duration_ms "
                "FROM api_keys ak LEFT JOIN request_logs rl ON rl.api_key_id = ak.id "
                "GROUP BY ak.id, ak.name ORDER BY total_calls DESC"
            )).mappings().all()
            return [ApiKeyStatsEntity(
                api_key_id=r["api_key_id"], api_key_name=r["api_key_name"],
                total_calls=int(r["total_calls"] or 0), success_calls=int(r["success_calls"] or 0),
                failed_calls=int(r["failed_calls"] or 0), total_tokens=int(r["total_tokens"] or 0),
                avg_duration_ms=float(r["avg_duration_ms"] or 0)
            ) for r in rows]

    # ---- ApiKey ----

    def get_all_api_keys(self) -> List[ApiKeyEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at "
                "FROM api_keys ORDER BY created_at DESC"
            )).mappings().all()
            return [self._to_apikey_entity(r) for r in rows]

    def get_api_key(self, key_id: str) -> Optional[ApiKeyEntity]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at "
                "FROM api_keys WHERE id = :id"
            ), {"id": key_id}).mappings().first()
            return self._to_apikey_entity(row) if row else None

    def get_api_key_by_key(self, key: str) -> Optional[ApiKeyEntity]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at "
                "FROM api_keys WHERE `key` = :key AND status = 1 LIMIT 1"
            ), {"key": key}).mappings().first()
            return self._to_apikey_entity(row) if row else None

    def create_api_key(self, entity: ApiKeyEntity) -> ApiKeyEntity:
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO api_keys (id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at) "
                "VALUES (:id, :name, :key, :status, :allowed_models, :allowed_channels, "
                ":quota_limit, :quota_used, :expires_at, :created_at, :updated_at)"
            ), self._to_apikey_params(entity))
        return entity

    def update_api_key(self, entity: ApiKeyEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE api_keys SET name=:name, `key`=:key, status=:status, "
                "allowed_models=:allowed_models, allowed_channels=:allowed_channels, "
                "quota_limit=:quota_limit, quota_used=:quota_used, expires_at=:expires_at, "
                "updated_at=:updated_at WHERE id=:id"
            ), self._to_apikey_params(entity))
            return result.rowcount > 0

    def delete_api_key(self, key_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM api_keys WHERE id = :id"), {"id": key_id})
            return result.rowcount > 0

    def increment_quota_used(self, key_id: str, delta: int) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "UPDATE api_keys SET quota_used = quota_used + :delta, updated_at=NOW() WHERE id=:id"
            ), {"id": key_id, "delta": delta})
            return result.rowcount > 0

    # ---- Conversions ----

    def _to_entity(self, row) -> ChannelEntity:
        return ChannelEntity(
            id=row["id"], name=row["name"], type=row["type"],
            base_url=row["base_url"], api_key=row["api_key"],
            models=json.loads(row["models"]) if row["models"] else [],
            status=row["status"], priority=row["priority"], weight=row["weight"],
            config=json.loads(row["config"]) if row["config"] else None,
            model_mapping=json.loads(row["model_mapping"]) if row["model_mapping"] else None,
            last_test_at=row["last_test_at"], last_test_ok=row["last_test_ok"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _to_params(self, e: ChannelEntity) -> dict:
        return {
            "id": e.id, "name": e.name, "type": e.type,
            "base_url": e.base_url, "api_key": e.api_key,
            "models": json.dumps(e.models or []),
            "status": e.status, "priority": e.priority, "weight": e.weight,
            "config": json.dumps(e.config or {}),
            "model_mapping": json.dumps(e.model_mapping or {}),
            "last_test_at": e.last_test_at, "last_test_ok": e.last_test_ok,
            "created_at": e.created_at, "updated_at": e.updated_at,
        }

    def _to_apikey_entity(self, row) -> ApiKeyEntity:
        return ApiKeyEntity(
            id=row["id"], name=row["name"], key=row["key"], status=row["status"],
            allowed_models=json.loads(row["allowed_models"]) if row["allowed_models"] else [],
            allowed_channels=json.loads(row["allowed_channels"]) if row["allowed_channels"] else [],
            quota_limit=row["quota_limit"], quota_used=row["quota_used"],
            expires_at=row["expires_at"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _to_apikey_params(self, e: ApiKeyEntity) -> dict:
        return {
            "id": e.id, "name": e.name, "key": e.key, "status": e.status,
            "allowed_models": json.dumps(e.allowed_models or []),
            "allowed_channels": json.dumps(e.allowed_channels or []),
            "quota_limit": e.quota_limit, "quota_used": e.quota_used,
            "expires_at": e.expires_at, "created_at": e.created_at, "updated_at": e.updated_at,
        }
