"""Agent repository."""
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import text

from app.infrastructure.database.connection import get_db
from app.domain.entities import AgentConfigEntity

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRepository:

    def get_all_agents(self) -> List[AgentConfigEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, agent_id, agent_name, agent_desc, app_name, config_json, status, created_at, updated_at "
                "FROM agent_configs ORDER BY created_at DESC"
            )).mappings().all()
            return [self._to_entity(r) for r in rows]

    def get_agent_by_id(self, agent_id: str) -> Optional[AgentConfigEntity]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, agent_id, agent_name, agent_desc, app_name, config_json, status, created_at, updated_at "
                "FROM agent_configs WHERE id = :id"
            ), {"id": agent_id}).mappings().first()
            return self._to_entity(row) if row else None

    def get_agent_by_agent_id(self, agent_id: str) -> Optional[AgentConfigEntity]:
        with get_db() as db:
            row = db.execute(text(
                "SELECT id, agent_id, agent_name, agent_desc, app_name, config_json, status, created_at, updated_at "
                "FROM agent_configs WHERE agent_id = :agent_id LIMIT 1"
            ), {"agent_id": agent_id}).mappings().first()
            return self._to_entity(row) if row else None

    def create_agent(self, entity: AgentConfigEntity) -> AgentConfigEntity:
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO agent_configs (id, agent_id, agent_name, agent_desc, app_name, config_json, status, created_at, updated_at) "
                "VALUES (:id, :agent_id, :agent_name, :agent_desc, :app_name, :config_json, :status, :created_at, :updated_at)"
            ), {
                "id": entity.id, "agent_id": entity.agent_id, "agent_name": entity.agent_name,
                "agent_desc": entity.agent_desc, "app_name": entity.app_name,
                "config_json": entity.config_json, "status": entity.status,
                "created_at": entity.created_at, "updated_at": entity.updated_at,
            })
        return entity

    def update_agent(self, entity: AgentConfigEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE agent_configs SET agent_id=:agent_id, agent_name=:agent_name, agent_desc=:agent_desc, "
                "app_name=:app_name, config_json=:config_json, status=:status, updated_at=:updated_at "
                "WHERE agent_id=:agent_id"
            ), {
                "id": entity.id, "agent_id": entity.agent_id, "agent_name": entity.agent_name,
                "agent_desc": entity.agent_desc, "app_name": entity.app_name,
                "config_json": entity.config_json, "status": entity.status,
                "created_at": entity.created_at, "updated_at": entity.updated_at,
            })
            return result.rowcount > 0

    def delete_agent(self, agent_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM agent_configs WHERE agent_id = :id"), {"id": agent_id})
            return result.rowcount > 0

    def _to_entity(self, row) -> AgentConfigEntity:
        return AgentConfigEntity(
            id=row["id"], agent_id=row["agent_id"], agent_name=row["agent_name"],
            agent_desc=row["agent_desc"], app_name=row["app_name"],
            config_json=row["config_json"], status=row["status"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
