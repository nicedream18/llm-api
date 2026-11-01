"""Cross-process routing capacity and circuit leases, serialized per resource."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


class RoutingRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def groups(self):
        with self.engine.connect() as db:
            return [{"id": row["id"], **json.loads(row["policy"]), "updated_at": row["updated_at"]} for row in db.execute(text("SELECT * FROM route_groups ORDER BY id")).mappings()]

    def policy(self, group):
        with self.engine.connect() as db:
            value = db.execute(text("SELECT policy FROM route_groups WHERE id=:id"), {"id": group}).scalar()
            return json.loads(value) if value else None

    def save_policy(self, group, policy):
        with self.engine.begin() as db:
            values = {"id": group, "policy": json.dumps(policy), "now": datetime.now(UTC).isoformat()}
            if self.engine.dialect.name == "mysql":
                sql = "INSERT INTO route_groups (id,policy,updated_at) VALUES (:id,:policy,:now) ON DUPLICATE KEY UPDATE policy=:policy,updated_at=:now"
            else:
                sql = "INSERT INTO route_groups (id,policy,updated_at) VALUES (:id,:policy,:now) ON CONFLICT(id) DO UPDATE SET policy=:policy,updated_at=:now"
            db.execute(text(sql), values)

    def _lock(self, db, resource):
        sql = "INSERT IGNORE" if self.engine.dialect.name == "mysql" else "INSERT OR IGNORE"
        db.execute(text(sql + " INTO route_runtime (resource_id) VALUES (:id)"), {"id": resource})
        suffix = " FOR UPDATE" if self.engine.dialect.name == "mysql" else ""
        return db.execute(text("SELECT * FROM route_runtime WHERE resource_id=:id" + suffix), {"id": resource}).mappings().one()

    def state(self, resource):
        now = datetime.now(UTC).isoformat()
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM route_runtime WHERE resource_id=:id"), {"id": resource}).mappings().first()
            active = db.execute(text("SELECT COUNT(*) FROM route_leases WHERE resource_id=:id AND expires_at>:now"), {"id": resource, "now": now}).scalar_one()
            return {**dict(row or {}), "active": active}

    def acquire(self, resource, limit=100, seconds=90):
        now = datetime.now(UTC)
        with self.engine.begin() as db:
            state = self._lock(db, resource)
            db.execute(text("DELETE FROM route_leases WHERE resource_id=:id AND expires_at<=:now"), {"id": resource, "now": now.isoformat()})
            active = db.execute(text("SELECT COUNT(*) FROM route_leases WHERE resource_id=:id"), {"id": resource}).scalar_one()
            if state["cooldown_until"] and state["cooldown_until"] > now.isoformat():
                return None
            if active >= limit or (state["failure_count"] and active):
                return None
            lease = {"id": uuid.uuid4().hex, "resource_id": resource, "generation": state["generation"]}
            db.execute(text("INSERT INTO route_leases (id,resource_id,generation,expires_at) VALUES (:id,:resource_id,:generation,:expires)"), {**lease, "expires": (now + timedelta(seconds=seconds)).isoformat()})
            return lease

    def renew(self, lease, seconds=90):
        now = datetime.now(UTC)
        with self.engine.begin() as db:
            return db.execute(text("UPDATE route_leases SET expires_at=:expires WHERE id=:id AND expires_at>:now"), {"id": lease["id"], "now": now.isoformat(), "expires": (now + timedelta(seconds=seconds)).isoformat()}).rowcount == 1

    def finish(self, lease, success=False, failure=False, retry_after=0):
        now = datetime.now(UTC)
        with self.engine.begin() as db:
            state = self._lock(db, lease["resource_id"])
            valid = db.execute(text("DELETE FROM route_leases WHERE id=:id AND expires_at>:now"), {"id": lease["id"], "now": now.isoformat()}).rowcount
            if not valid:
                return False
            values = {"id": lease["resource_id"]}
            if failure:
                delay = max(min(300, 2 ** min(state["failure_count"] + 1, 8)), min(300, retry_after))
                db.execute(text("UPDATE route_runtime SET generation=generation+1,failure_count=failure_count+1,error_count=error_count+1,cooldown_until=:until WHERE resource_id=:id"), {**values, "until": (now + timedelta(seconds=delay)).isoformat()})
            elif success:
                clear = ",failure_count=0,cooldown_until=NULL" if state["generation"] == lease["generation"] else ""
                db.execute(text("UPDATE route_runtime SET success_count=success_count+1" + clear + " WHERE resource_id=:id"), values)
            return True
