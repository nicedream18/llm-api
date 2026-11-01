"""Persistence for software connector instances, tools and calls."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import bindparam, inspect, text

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
            dialect = getattr(getattr(db, "bind", None), "dialect", None)
            lock_suffix = " FOR UPDATE" if getattr(dialect, "name", None) == "mysql" else ""
            exists = db.execute(
                text("SELECT id FROM software_instances WHERE id=:id" + lock_suffix),
                {"id": instance_id},
            ).first()
            if not exists:
                return False
            # Legacy installations do not necessarily have foreign keys, so
            # dependent rows are removed explicitly in the same transaction.
            if inspect(db).has_table("software_approval_requests"):
                db.execute(text("DELETE FROM software_approval_requests WHERE tool_id IN (SELECT id FROM software_tools WHERE instance_id=:id)"), {"id": instance_id})
            db.execute(text("DELETE FROM software_call_logs WHERE tool_id IN (SELECT id FROM software_tools WHERE instance_id=:id)"), {"id": instance_id})
            db.execute(text("DELETE FROM software_tools WHERE instance_id=:id"), {"id": instance_id})
            return db.execute(
                text("DELETE FROM software_instances WHERE id=:id"),
                {"id": instance_id},
            ).rowcount > 0

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

    def import_openapi(self, instance_values, tools):
        """Create an OpenAPI instance and its selected tools atomically."""
        instance = {"id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now(), **instance_values}
        instance["config"] = json.dumps(instance.get("config") or {}, ensure_ascii=False)
        tool_rows = []
        for values in tools:
            row = {"id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now(), **values}
            row["instance_id"] = instance["id"]
            row.setdefault("description", "")
            row.setdefault("risk_level", "medium")
            row.setdefault("approval_mode", "per_call")
            row.setdefault("enabled", 1)
            row["input_schema"] = json.dumps(row.get("input_schema") or {}, ensure_ascii=False)
            row["config"] = json.dumps(row.get("config") or {}, ensure_ascii=False)
            tool_rows.append(row)
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_instances
                (id,name,connector_type,config,enabled,created_at,updated_at)
                VALUES (:id,:name,:connector_type,:config,:enabled,:created_at,:updated_at)"""), instance)
            for row in tool_rows:
                db.execute(text("""INSERT INTO software_tools
                    (id,instance_id,name,description,input_schema,risk_level,approval_mode,config,enabled,created_at,updated_at)
                    VALUES (:id,:instance_id,:name,:description,:input_schema,:risk_level,:approval_mode,:config,:enabled,:created_at,:updated_at)"""), row)
        return {"instance": self.get_instance(instance["id"]), "tools": self.list_tools(instance["id"])}

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
        row = {
            "id": str(uuid.uuid4()),
            "principal_type": None,
            "principal_id": None,
            "error_type": None,
            "duration_ms": 0,
            "request_summary": None,
            "response_summary": None,
            "created_at": _now(),
            **values,
        }
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_call_logs
                (id,tool_id,principal_type,principal_id,status,error_type,duration_ms,request_summary,response_summary,created_at)
                VALUES (:id,:tool_id,:principal_type,:principal_id,:status,:error_type,:duration_ms,:request_summary,:response_summary,:created_at)"""), row)
        return row

    def list_calls(self, limit=100):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM software_call_logs ORDER BY created_at DESC, id DESC LIMIT :limit"), {"limit": min(max(int(limit), 1), 500)}).mappings()]

    def create_approval(self, values):
        row = {"id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now(), **values}
        expires_at = row.pop("expires_at", None)
        row["arguments"] = json.dumps(row.get("arguments") or {}, ensure_ascii=False)
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO software_approval_requests
                (id,tool_id,principal_type,principal_id,arguments,status,decision_by,decision_at,error_type,created_at,updated_at)
                VALUES (:id,:tool_id,:principal_type,:principal_id,:arguments,:status,:decision_by,:decision_at,:error_type,:created_at,:updated_at)"""), row)
            if expires_at is not None and inspect(db).has_table("software_approval_expiry"):
                db.execute(text("""INSERT INTO software_approval_expiry (approval_id, expires_at, created_at)
                    VALUES (:approval_id, :expires_at, :created_at)"""),
                    {"approval_id": row["id"], "expires_at": expires_at, "created_at": row["created_at"]})
        return self.get_approval(row["id"])

    def get_approval(self, approval_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM software_approval_requests WHERE id=:id"), {"id": approval_id}).mappings().first()
            if not row:
                return None
            result = dict(row)
            if inspect(db).has_table("software_approval_expiry"):
                expiry = db.execute(text("SELECT expires_at FROM software_approval_expiry WHERE approval_id=:id"), {"id": approval_id}).scalar()
                if expiry is not None:
                    result["expires_at"] = expiry
            return result

    def list_approvals(self, status=None, limit=100):
        query = "SELECT * FROM software_approval_requests"
        params = {"limit": min(max(int(limit), 1), 500)}
        if status:
            query += " WHERE status=:status"
            params["status"] = status
        query += " ORDER BY created_at DESC, id DESC LIMIT :limit"
        with self.engine.connect() as db:
            rows = [dict(row) for row in db.execute(text(query), params).mappings()]
            if inspect(db).has_table("software_approval_expiry") and rows:
                ids = [row["id"] for row in rows]
                expiry_query = text(
                    "SELECT approval_id, expires_at FROM software_approval_expiry WHERE approval_id IN :ids"
                ).bindparams(bindparam("ids", expanding=True))
                expiry_rows = db.execute(expiry_query, {"ids": ids}).mappings()
                expiry_by_id = {row["approval_id"]: row["expires_at"] for row in expiry_rows}
                for row in rows:
                    if row["id"] in expiry_by_id:
                        row["expires_at"] = expiry_by_id[row["id"]]
            return rows

    def update_approval(self, approval_id, values, expected_status=None):
        values = {**values, "updated_at": _now(), "id": approval_id}
        if "arguments" in values:
            values["arguments"] = json.dumps(values["arguments"] or {}, ensure_ascii=False)
        fields = ", ".join(f"{key}=:{key}" for key in values if key != "id")
        where = "id=:id"
        if expected_status:
            where += " AND status=:expected_status"
            values["expected_status"] = expected_status
        with self.engine.begin() as db:
            changed = db.execute(text(f"UPDATE software_approval_requests SET {fields} WHERE {where}"), values).rowcount
        return changed == 1
