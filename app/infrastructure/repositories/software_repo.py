"""Persistence for software connector instances, tools and calls."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


def _now():
    return datetime.now(UTC).isoformat()


class SoftwareRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def list_instances(self):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM software_instances ORDER BY created_at, id")).mappings()]

    def get_instance(self, instance_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM software_instances WHERE id=:id"), {"id": instance_id}).mappings().first()
            return dict(row) if row else None

    def create_instance(self, values):
        row = {"id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now(), **values}
        row["config"] = json.dumps(row.get("config") or {}, ensure_ascii=False)
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_instances
                (id,name,connector_type,config,enabled,created_at,updated_at)
                VALUES (:id,:name,:connector_type,:config,:enabled,:created_at,:updated_at)"""), row)
        return self.get_instance(row["id"])

    def update_instance(self, instance_id, values):
        values = {**values, "updated_at": _now(), "id": instance_id}
        if "config" in values:
            values["config"] = json.dumps(values["config"] or {}, ensure_ascii=False)
        fields = ", ".join(f"{key}=:{key}" for key in values if key != "id")
        with self.engine.begin() as db:
            db.execute(text(f"UPDATE software_instances SET {fields} WHERE id=:id"), values)
        return self.get_instance(instance_id)

    def delete_instance(self, instance_id):
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM software_instances WHERE id=:id"), {"id": instance_id}).rowcount > 0

    def list_tools(self, instance_id=None):
        query = "SELECT * FROM software_tools" + (" WHERE instance_id=:instance_id" if instance_id else "") + " ORDER BY created_at, id"
        with self.engine.connect() as db:
            rows = db.execute(text(query), {"instance_id": instance_id} if instance_id else {}).mappings()
            return [dict(row) for row in rows]

    def get_tool(self, tool_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM software_tools WHERE id=:id"), {"id": tool_id}).mappings().first()
            return dict(row) if row else None

    def create_tool(self, values):
        row = {"id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now(), **values}
        for key in ("input_schema", "config"):
            row[key] = json.dumps(row.get(key) or {}, ensure_ascii=False)
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_tools
                (id,instance_id,name,description,input_schema,risk_level,approval_mode,config,enabled,created_at,updated_at)
                VALUES (:id,:instance_id,:name,:description,:input_schema,:risk_level,:approval_mode,:config,:enabled,:created_at,:updated_at)"""), row)
        return self.get_tool(row["id"])

    def update_tool(self, tool_id, values):
        values = {**values, "updated_at": _now(), "id": tool_id}
        for key in ("input_schema", "config"):
            if key in values:
                values[key] = json.dumps(values[key] or {}, ensure_ascii=False)
        fields = ", ".join(f"{key}=:{key}" for key in values if key != "id")
        with self.engine.begin() as db:
            db.execute(text(f"UPDATE software_tools SET {fields} WHERE id=:id"), values)
        return self.get_tool(tool_id)

    def delete_tool(self, tool_id):
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM software_tools WHERE id=:id"), {"id": tool_id}).rowcount > 0

    def record_call(self, values):
        row = {"id": str(uuid.uuid4()), "created_at": _now(), **values}
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_call_logs
                (id,tool_id,principal_type,principal_id,status,error_type,duration_ms,request_summary,response_summary,created_at)
                VALUES (:id,:tool_id,:principal_type,:principal_id,:status,:error_type,:duration_ms,:request_summary,:response_summary,:created_at)"""), row)
        return row

    def list_calls(self, limit=100):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM software_call_logs ORDER BY created_at DESC, id DESC LIMIT :limit"), {"limit": min(max(int(limit), 1), 500)}).mappings()]
