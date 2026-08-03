"""Security repository for findings, builtin rules, custom rules."""
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import text

from app.infrastructure.database.connection import get_db
from app.domain.entities import SecurityFindingEntity, SecurityBuiltinRuleEntity, SecurityCustomRuleEntity

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SecurityRepository:

    def save_findings(self, findings: List[SecurityFindingEntity]):
        if not findings:
            return
        params_list = []
        for f in findings:
            if not f.id:
                f.id = str(uuid.uuid4())
            if not f.created_at:
                f.created_at = _now()
            params_list.append({
                "id": f.id, "log_id": f.log_id, "phase": f.phase, "category": f.category,
                "rule_id": f.rule_id, "severity": f.severity, "title": f.title,
                "description": f.description, "location": f.location,
                "evidence_masked": f.evidence_masked, "evidence_hash": f.evidence_hash,
                "action": f.action, "created_at": f.created_at,
            })
        with get_db() as db:
            for p in params_list:
                db.execute(text(
                    "INSERT INTO security_findings (id, log_id, phase, category, rule_id, severity, "
                    "title, description, location, evidence_masked, evidence_hash, action, created_at) "
                    "VALUES (:id, :log_id, :phase, :category, :rule_id, :severity, "
                    ":title, :description, :location, :evidence_masked, :evidence_hash, :action, :created_at)"
                ), p)

    def get_findings_by_log_id(self, log_id: str) -> List[SecurityFindingEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, log_id, phase, category, rule_id, severity, title, description, "
                "location, evidence_masked, evidence_hash, action, created_at "
                "FROM security_findings WHERE log_id = :log_id ORDER BY created_at ASC"
            ), {"log_id": log_id}).mappings().all()
            return [self._to_finding_entity(r) for r in rows]

    def get_all_findings(self, offset: int, limit: int) -> List[SecurityFindingEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, log_id, phase, category, rule_id, severity, title, description, "
                "location, evidence_masked, evidence_hash, action, created_at "
                "FROM security_findings ORDER BY created_at DESC LIMIT :offset, :limit"
            ), {"offset": offset, "limit": limit}).mappings().all()
            return [self._to_finding_entity(r) for r in rows]

    def count_findings(self) -> int:
        with get_db() as db:
            row = db.execute(text("SELECT COUNT(*) AS cnt FROM security_findings")).mappings().first()
            return int(row["cnt"]) if row else 0

    def get_all_builtin_rules(self) -> List[SecurityBuiltinRuleEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, category, rule_id, name, description, severity, pattern, action, "
                "enabled, created_at, updated_at FROM security_builtin_rules "
                "ORDER BY category ASC, created_at ASC"
            )).mappings().all()
            return [self._to_builtin_entity(r) for r in rows]

    def update_builtin_rule(self, rule_id: str, enabled: Optional[int], severity: Optional[str]) -> bool:
        with get_db() as db:
            if severity:
                result = db.execute(text(
                    "UPDATE security_builtin_rules SET enabled=:enabled, severity=:severity, updated_at=NOW() WHERE id=:id"
                ), {"id": rule_id, "enabled": enabled, "severity": severity})
            else:
                result = db.execute(text(
                    "UPDATE security_builtin_rules SET enabled=:enabled, updated_at=NOW() WHERE id=:id"
                ), {"id": rule_id, "enabled": enabled})
            return result.rowcount > 0

    def get_all_custom_rules(self) -> List[SecurityCustomRuleEntity]:
        with get_db() as db:
            rows = db.execute(text(
                "SELECT id, category, name, description, severity, pattern, action, "
                "enabled, created_at, updated_at FROM security_custom_rules ORDER BY created_at DESC"
            )).mappings().all()
            return [self._to_custom_entity(r) for r in rows]

    def create_custom_rule(self, entity: SecurityCustomRuleEntity) -> SecurityCustomRuleEntity:
        if not entity.id:
            entity.id = str(uuid.uuid4())
        now = _now()
        if not entity.created_at:
            entity.created_at = now
        entity.updated_at = now
        with get_db() as db:
            db.execute(text(
                "INSERT INTO security_custom_rules (id, category, name, description, severity, "
                "pattern, action, enabled, created_at, updated_at) "
                "VALUES (:id, :category, :name, :description, :severity, :pattern, :action, :enabled, :created_at, :updated_at)"
            ), self._to_custom_params(entity))
        return entity

    def update_custom_rule(self, entity: SecurityCustomRuleEntity) -> bool:
        entity.updated_at = _now()
        with get_db() as db:
            result = db.execute(text(
                "UPDATE security_custom_rules SET category=:category, name=:name, description=:description, "
                "severity=:severity, pattern=:pattern, action=:action, enabled=:enabled, updated_at=:updated_at WHERE id=:id"
            ), self._to_custom_params(entity))
            return result.rowcount > 0

    def delete_custom_rule(self, rule_id: str) -> bool:
        with get_db() as db:
            result = db.execute(text("DELETE FROM security_custom_rules WHERE id = :id"), {"id": rule_id})
            return result.rowcount > 0

    def _to_finding_entity(self, row) -> SecurityFindingEntity:
        return SecurityFindingEntity(
            id=row["id"], log_id=row["log_id"], phase=row["phase"], category=row["category"],
            rule_id=row["rule_id"], severity=row["severity"], title=row["title"],
            description=row["description"], location=row["location"],
            evidence_masked=row["evidence_masked"], evidence_hash=row["evidence_hash"],
            action=row["action"], created_at=row["created_at"],
        )

    def _to_builtin_entity(self, row) -> SecurityBuiltinRuleEntity:
        return SecurityBuiltinRuleEntity(
            id=row["id"], category=row["category"], rule_id=row["rule_id"], name=row["name"],
            description=row["description"], severity=row["severity"], pattern=row["pattern"],
            action=row["action"], enabled=row["enabled"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _to_custom_entity(self, row) -> SecurityCustomRuleEntity:
        return SecurityCustomRuleEntity(
            id=row["id"], category=row["category"], name=row["name"], description=row["description"],
            severity=row["severity"], pattern=row["pattern"], action=row["action"],
            enabled=row["enabled"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def _to_custom_params(self, e: SecurityCustomRuleEntity) -> dict:
        return {
            "id": e.id, "category": e.category, "name": e.name, "description": e.description,
            "severity": e.severity, "pattern": e.pattern, "action": e.action,
            "enabled": e.enabled, "created_at": e.created_at, "updated_at": e.updated_at,
        }
