"""Append-only usage facts. Log cleanup cannot delete or rewrite this ledger."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.application.errors import ApplicationError
from app.infrastructure.database.connection import engine as default_engine


class UsageRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def prices(self):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM price_versions ORDER BY effective_at DESC,id DESC")).mappings()]

    def add_price(self, dto):
        values = {"id": uuid.uuid4().hex, **dto.model_dump(mode="json"), "created_at": datetime.now(UTC).isoformat()}
        values["effective_at"] = dto.effective_at.isoformat()
        with self.engine.begin() as db:
            db.execute(text("""INSERT INTO price_versions (id,provider,model,currency,input_per_million,output_per_million,effective_at,created_at)
                VALUES (:id,:provider,:model,:currency,:input_per_million,:output_per_million,:effective_at,:created_at)"""), values)
        return values

    def append(self, fact):
        values = fact.model_dump()
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        fact_id = hashlib.sha256(f"{fact.execution_id}:{fact.event_key}".encode()).hexdigest()
        with self.engine.begin() as db:
            price = db.execute(text("""SELECT * FROM price_versions WHERE provider=:provider AND model=:model
                AND effective_at<=:when ORDER BY effective_at DESC,created_at DESC,id DESC LIMIT 1"""),
                {"provider": fact.provider, "model": fact.model, "when": fact.occurred_at}).mappings().first() if fact.kind == "attempt" else None
            cost = None
            pricing = "not_applicable" if fact.kind == "outcome" else "missing_price" if not price else "unknown_usage"
            if price and fact.input_tokens is not None and fact.output_tokens is not None:
                cost = str((Decimal(fact.input_tokens) * Decimal(price["input_per_million"]) + Decimal(fact.output_tokens) * Decimal(price["output_per_million"])) / Decimal(1_000_000))
                pricing = "estimated" if fact.usage_source == "estimated" else "priced"
            row = {**values, "id": fact_id, "payload_hash": digest, "price_version": price["id"] if price else None,
                   "currency": price["currency"] if price else None, "cost": cost, "pricing_status": pricing}
            fields = ",".join(row)
            try:
                with db.begin_nested():
                    db.execute(text(f"INSERT INTO usage_ledger ({fields}) VALUES ({','.join(':' + key for key in row)})"), row)
            except IntegrityError:
                suffix = " FOR UPDATE" if db.engine.dialect.name == "mysql" else ""
                existing = db.execute(text("SELECT payload_hash FROM usage_ledger WHERE id=:id" + suffix), {"id": fact_id}).scalar()
                if existing != digest:
                    raise ApplicationError("Usage event conflicts with an existing fact", 409, "usage_conflict") from None
                return False
            return True

    def execution(self, execution_id):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM usage_ledger WHERE execution_id=:id ORDER BY occurred_at,event_key"), {"id": execution_id}).mappings()]

    def by_request(self, request_id):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("SELECT * FROM usage_ledger WHERE request_id=:id ORDER BY occurred_at,event_key"), {"id": request_id}).mappings()]
