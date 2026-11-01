"""Durable alert episodes, serialized deduplication and acknowledgement history."""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.application.errors import ApplicationError
from app.infrastructure.database.connection import engine as default_engine


class AlertRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def rules(self):
        with self.engine.connect() as db:
            return [{"id": row["id"], **json.loads(row["policy"])} for row in db.execute(text("SELECT * FROM alert_rules ORDER BY id")).mappings()]

    def save_rule(self, rule_id, policy):
        with self.engine.begin() as db:
            if db.engine.dialect.name == "mysql":
                sql = "INSERT INTO alert_rules (id,policy) VALUES (:id,:policy) ON DUPLICATE KEY UPDATE policy=:policy"
            else:
                sql = "INSERT INTO alert_rules (id,policy) VALUES (:id,:policy) ON CONFLICT(id) DO UPDATE SET policy=:policy"
            db.execute(text(sql), {"id": rule_id, "policy": json.dumps(policy)})

    def _event(self, db, alert_id, action, principal="system"):
        db.execute(text("INSERT INTO alert_events (id,alert_id,action,principal,created_at) VALUES (:id,:alert,:action,:principal,:now)"),
            {"id": uuid.uuid4().hex, "alert": alert_id, "action": action, "principal": principal, "now": datetime.now(UTC).isoformat()})

    def transition(self, fingerprint, active, severity="warning", message=""):
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as db:
            insert = "INSERT IGNORE" if db.engine.dialect.name == "mysql" else "INSERT OR IGNORE"
            db.execute(text(insert + " INTO alert_runtime (fingerprint) VALUES (:key)"), {"key": fingerprint})
            suffix = " FOR UPDATE" if db.engine.dialect.name == "mysql" else ""
            alert_id = db.execute(text("SELECT active_id FROM alert_runtime WHERE fingerprint=:key" + suffix), {"key": fingerprint}).scalar()
            if active and alert_id:
                db.execute(text("UPDATE operational_alerts SET last_seen_at=:now WHERE id=:id"), {"id": alert_id, "now": now})
            elif active:
                alert_id = uuid.uuid4().hex
                db.execute(text("""INSERT INTO operational_alerts (id,fingerprint,severity,message,status,opened_at,last_seen_at)
                    VALUES (:id,:key,:severity,:message,'open',:now,:now)"""), {"id": alert_id, "key": fingerprint, "severity": severity, "message": message, "now": now})
                db.execute(text("UPDATE alert_runtime SET active_id=:id WHERE fingerprint=:key"), {"id": alert_id, "key": fingerprint})
                self._event(db, alert_id, "opened")
            elif alert_id:
                db.execute(text("UPDATE operational_alerts SET status='resolved',resolved_at=:now WHERE id=:id"), {"id": alert_id, "now": now})
                db.execute(text("UPDATE alert_runtime SET active_id=NULL WHERE fingerprint=:key"), {"key": fingerprint})
                self._event(db, alert_id, "resolved")
            return alert_id

    def acknowledge(self, alert_id, principal):
        with self.engine.begin() as db:
            changed = db.execute(text("UPDATE operational_alerts SET status='acknowledged' WHERE id=:id AND status='open'"), {"id": alert_id}).rowcount
            if changed:
                self._event(db, alert_id, "acknowledged", principal)
            elif not db.execute(text("SELECT id FROM operational_alerts WHERE id=:id"), {"id": alert_id}).first():
                raise ApplicationError("Alert not found", 404, "not_found")
            return bool(changed)

    def list(self, limit=50, offset=0):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM operational_alerts ORDER BY last_seen_at DESC,id DESC LIMIT :limit OFFSET :offset"), {"limit": limit, "offset": offset}).mappings()]

    def active_fingerprints(self, prefix):
        with self.engine.connect() as db:
            return [row[0] for row in db.execute(text("SELECT fingerprint FROM alert_runtime WHERE active_id IS NOT NULL AND fingerprint LIKE :prefix"), {"prefix": prefix + ":%"})]

    def events(self, alert_id, limit=100):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM alert_events WHERE alert_id=:id ORDER BY created_at,id LIMIT :limit"), {"id": alert_id, "limit": limit}).mappings()]
