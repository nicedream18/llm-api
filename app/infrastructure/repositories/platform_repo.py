"""Persistence for prompts, semantic cache and application settings."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.infrastructure.database.connection import engine as default_engine


def _now():
    return datetime.now(UTC).isoformat()


class PlatformRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def list_prompts(self):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM prompt_templates ORDER BY name, version DESC")).mappings()]

    def get_prompt(self, prompt_id):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM prompt_templates WHERE id=:id"), {"id": prompt_id}).mappings().first()
            return dict(row) if row else None

    def create_prompt(self, values):
        row = {"id": str(uuid.uuid4()), "version": 1, "created_at": _now(), "updated_at": _now(), **values}
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO prompt_templates
                (id,name,description,template,version,enabled,created_at,updated_at)
                VALUES (:id,:name,:description,:template,:version,:enabled,:created_at,:updated_at)"""), row)
        return self.get_prompt(row["id"])

    def update_prompt(self, prompt_id, values):
        values = {**values, "id": prompt_id, "updated_at": _now()}
        fields = ", ".join(f"{key}=:{key}" for key in values if key != "id")
        with self.engine.begin() as db:
            db.execute(text(f"UPDATE prompt_templates SET {fields}, version=version+1 WHERE id=:id"), values)
        return self.get_prompt(prompt_id)

    def delete_prompt(self, prompt_id):
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM prompt_templates WHERE id=:id"), {"id": prompt_id}).rowcount > 0

    def get_cache(self, cache_key):
        with self.engine.connect() as db:
            row = db.execute(text("SELECT * FROM semantic_cache WHERE cache_key=:cache_key"), {"cache_key": cache_key}).mappings().first()
            return dict(row) if row else None

    def put_cache(self, values):
        row = {"id": str(uuid.uuid4()), "created_at": _now(), **values}
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM semantic_cache WHERE cache_key=:cache_key"), {"cache_key": row["cache_key"]})
            db.execute(text("""INSERT INTO semantic_cache
                (id,cache_key,model,scope,request,response,expires_at,created_at)
                VALUES (:id,:cache_key,:model,:scope,:request,:response,:expires_at,:created_at)"""), row)
        return row

    def clear_cache(self):
        with self.engine.begin() as db:
            return db.execute(text("DELETE FROM semantic_cache")).rowcount
