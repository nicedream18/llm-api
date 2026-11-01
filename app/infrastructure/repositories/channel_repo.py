"""Channel and ApiKey repository."""
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.domain.entities import (
    ApiKeyEntity,
    ApiKeyStatsEntity,
    ChannelApiKeyEntity,
    ChannelEntity,
    ChannelStatsEntity,
)
from app.infrastructure.database.connection import affected_rows, get_db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ChannelRepository:

    def get_all_channels(self) -> list[ChannelEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at "
                "FROM channels ORDER BY priority DESC, created_at DESC"
            )).mappings().all()
            return [self._to_entity(r) for r in rows]

    def get_channel(self, channel_id: str) -> ChannelEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, type, base_url, api_key, models, status, priority, weight, "
                "config, model_mapping, last_test_at, last_test_ok, created_at, updated_at "
                "FROM channels WHERE id = :id"
            ), {"id": channel_id}).mappings().first()
            return self._to_entity(row) if row else None

    def get_enabled_channels(self) -> list[ChannelEntity]:
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
            self._replace_channel_keys(db, entity.id or "", entity.api_keys)
        return entity

    def update_channel(self, entity: ChannelEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET name=:name, type=:type, base_url=:base_url, api_key=:api_key, "
                "models=:models, status=:status, priority=:priority, weight=:weight, "
                "config=:config, model_mapping=:model_mapping, updated_at=:updated_at WHERE id=:id"
            ), self._to_params(entity))
            if entity.api_keys is not None:
                self._replace_channel_keys(db, entity.id or "", entity.api_keys)
            return affected_rows(result) > 0

    def delete_channel(self, channel_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM channels WHERE id = :id"), {"id": channel_id})
            return affected_rows(result) > 0

    def toggle_channel_status(self, channel_id: str, status: int) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET status=:status, updated_at=NOW() WHERE id=:id"
            ), {"id": channel_id, "status": status})
            return affected_rows(result) > 0

    def update_test_result(self, channel_id: str, ok: bool) -> bool:
        now = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channels SET last_test_at=:t, last_test_ok=:ok, updated_at=:t WHERE id=:id"
            ), {"id": channel_id, "t": now, "ok": 1 if ok else 0})
            return affected_rows(result) > 0

    def get_channel_api_keys(self, channel_id: str) -> list[ChannelApiKeyEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, channel_id, name, api_key, status, weight, last_error, cooldown_until, "
                "last_used_at, created_at, updated_at FROM channel_api_keys "
                "WHERE channel_id=:channel_id ORDER BY created_at ASC"
            ), {"channel_id": channel_id}).mappings().all()
            return [self._to_channel_key(r) for r in rows]

    def create_channel_api_key(self, entity: ChannelApiKeyEntity) -> ChannelApiKeyEntity:
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        entity.created_at = entity.created_at or now
        entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO channel_api_keys (id, channel_id, name, api_key, status, weight, last_error, "
                "cooldown_until, last_used_at, created_at, updated_at) VALUES "
                "(:id, :channel_id, :name, :api_key, :status, :weight, :last_error, :cooldown_until, "
                ":last_used_at, :created_at, :updated_at)"
            ), self._channel_key_params(entity))
        return entity

    def update_channel_api_key(self, entity: ChannelApiKeyEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channel_api_keys SET name=:name, api_key=:api_key, status=:status, weight=:weight, "
                "last_error=:last_error, cooldown_until=:cooldown_until, last_used_at=:last_used_at, "
                "updated_at=:updated_at WHERE id=:id AND channel_id=:channel_id"
            ), self._channel_key_params(entity))
            return affected_rows(result) > 0

    def delete_channel_api_key(self, channel_id: str, key_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "DELETE FROM channel_api_keys WHERE id=:id AND channel_id=:channel_id"
            ), {"id": key_id, "channel_id": channel_id})
            return affected_rows(result) > 0

    def update_channel_api_key_result(self, key_id: str, ok: bool, error: str | None = None, cooldown_until: str | None = None) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "UPDATE channel_api_keys SET last_error=:last_error, cooldown_until=:cooldown_until, "
                "last_used_at=:last_used_at, updated_at=:last_used_at WHERE id=:id"
            ), {"id": key_id, "last_error": None if ok else error, "cooldown_until": cooldown_until,
                "last_used_at": _now()})
            return affected_rows(result) > 0

    def get_channel_stats(self) -> list[ChannelStatsEntity]:
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

    def get_api_key_stats(self) -> list[ApiKeyStatsEntity]:
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

    def get_all_api_keys(self) -> list[ApiKeyEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at "
                "FROM api_keys ORDER BY created_at DESC"
            )).mappings().all()
            return [self._to_apikey_entity(r) for r in rows]

    def get_api_key(self, key_id: str) -> ApiKeyEntity | None:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, name, `key`, status, allowed_models, allowed_channels, "
                "quota_limit, quota_used, expires_at, created_at, updated_at "
                "FROM api_keys WHERE id = :id"
            ), {"id": key_id}).mappings().first()
            return self._to_apikey_entity(row) if row else None

    def get_api_key_by_key(self, key: str) -> ApiKeyEntity | None:
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
                "quota_limit=:quota_limit, expires_at=:expires_at, "
                "updated_at=:updated_at WHERE id=:id"
            ), self._to_apikey_params(entity))
            return affected_rows(result) > 0

    def delete_api_key(self, key_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM api_keys WHERE id = :id"), {"id": key_id})
            return affected_rows(result) > 0

    def increment_quota_used(self, key_id: str, delta: int) -> bool:
        with get_db() as db:
            result = db.execute(text(
                "UPDATE api_keys SET quota_used = quota_used + :delta, updated_at=NOW() WHERE id=:id"
            ), {"id": key_id, "delta": delta})
            return affected_rows(result) > 0

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
            api_keys=self.get_channel_api_keys(row["id"]),
        )

    @staticmethod
    def _to_channel_key(row) -> ChannelApiKeyEntity:
        return ChannelApiKeyEntity(
            id=row["id"], channel_id=row["channel_id"], name=row["name"], api_key=row["api_key"],
            status=row["status"], weight=row["weight"], last_error=row["last_error"],
            cooldown_until=row["cooldown_until"], last_used_at=row["last_used_at"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _channel_key_params(entity: ChannelApiKeyEntity) -> dict:
        return {
            "id": entity.id, "channel_id": entity.channel_id, "name": entity.name,
            "api_key": entity.api_key, "status": entity.status, "weight": entity.weight,
            "last_error": entity.last_error, "cooldown_until": entity.cooldown_until,
            "last_used_at": entity.last_used_at, "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

    @classmethod
    def _replace_channel_keys(cls, db, channel_id: str, keys: list[ChannelApiKeyEntity]) -> None:
        db.execute(text("DELETE FROM channel_api_keys WHERE channel_id=:channel_id"), {"channel_id": channel_id})
        for key in keys or []:
            key.channel_id = channel_id
            if not key.id:
                key.id = str(uuid.uuid4())
            now = _now()
            key.created_at = key.created_at or now
            key.updated_at = now
            db.execute(text(
                "INSERT INTO channel_api_keys (id, channel_id, name, api_key, status, weight, last_error, "
                "cooldown_until, last_used_at, created_at, updated_at) VALUES "
                "(:id, :channel_id, :name, :api_key, :status, :weight, :last_error, :cooldown_until, "
                ":last_used_at, :created_at, :updated_at)"
            ), cls._channel_key_params(key))

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
