"""Quota/model snapshots and a bounded durable synchronization queue."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.application.errors import ApplicationError


class ProviderSyncRepository:
    def synchronization_state(self, account_id):
        with self.engine.connect() as db:
            snapshots = {}
            for row in db.execute(text("SELECT * FROM provider_snapshots WHERE account_id=:id"), {"id": account_id}).mappings():
                snapshots[row["kind"]] = {**dict(row), "payload": json.loads(row["payload"]) if row["payload"] else None}
            settings = db.execute(text("SELECT * FROM provider_sync_settings WHERE account_id=:id"), {"id": account_id}).mappings().first()
            jobs = db.execute(text("SELECT * FROM provider_sync_jobs WHERE account_id=:id ORDER BY kind"), {"id": account_id}).mappings()
            generation = db.execute(text("SELECT generation FROM provider_auth_runtime WHERE account_id=:id"), {"id": account_id}).scalar()
            return {"snapshots": snapshots, "generation": generation, "settings": dict(settings) if settings else {"enabled": False, "quota_interval": 300, "models_interval": 21600}, "jobs": [dict(row) for row in jobs]}

    def read_sync_credentials(self, account_id):
        with self.engine.begin() as db:
            account = dict(self._lock(db, account_id))
            token = db.execute(text("SELECT * FROM provider_tokens WHERE account_id=:id"), {"id": account_id}).mappings().first()
            if token is None or account["status"] != "active" or self._profile(db, account_id)["archived_at"]:
                raise ApplicationError("Provider account is not connected", 409, "provider_disconnected")
            return account, dict(token), self._runtime(db, account_id)["generation"]

    def save_snapshot(self, account_id, kind, generation, payload=None, error=None, job=None, requested_at=None):
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as db:
            account = self._lock(db, account_id)
            if self._runtime(db, account_id)["generation"] != generation or account["status"] != "active":
                raise ApplicationError("Provider authorization changed", 409, "authorization_changed")
            if job:
                suffix = " FOR UPDATE" if db.engine.dialect.name == "mysql" else ""
                valid = db.execute(text("""SELECT id FROM provider_sync_jobs WHERE id=:id
                    AND lease_owner=:owner AND attempts=:attempts AND status='running' AND lease_until>:now""" + suffix), {
                    "id": job["id"], "owner": job["lease_owner"], "attempts": job["attempts"], "now": now,
                }).first()
                if not valid:
                    raise ApplicationError("Synchronization lease expired", 409, "sync_lease_expired")
            requested_at = requested_at or now
            exists = db.execute(text("SELECT last_attempt_at FROM provider_snapshots WHERE account_id=:id AND kind=:kind"), {"id": account_id, "kind": kind}).first()
            if exists and exists[0] > requested_at:
                return False
            if not exists:
                db.execute(text("""INSERT INTO provider_snapshots (account_id,kind,generation,last_attempt_at)
                    VALUES (:id,:kind,:generation,:now)"""), {"id": account_id, "kind": kind, "generation": generation, "now": now})
            values = {"id": account_id, "kind": kind, "now": now, "requested_at": requested_at, "error": error, "generation": generation}
            extra = ""
            if payload is not None:
                values["payload"] = json.dumps(payload, ensure_ascii=False)
                extra = ",payload=:payload,fetched_at=:now,generation=:generation"
            db.execute(text("UPDATE provider_snapshots SET last_attempt_at=:requested_at,error_code=:error" + extra + " WHERE account_id=:id AND kind=:kind"), values)
            return True

    def configure_sync(self, account_id, settings):
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as db:
            self._lock(db, account_id)
            db.execute(text("DELETE FROM provider_sync_settings WHERE account_id=:id"), {"id": account_id})
            db.execute(text("""INSERT INTO provider_sync_settings
                (account_id,enabled,quota_interval,models_interval,next_quota_at,next_models_at)
                VALUES (:id,:enabled,:quota_interval,:models_interval,:now,:now)"""), {"id": account_id, "now": now, **settings})

    def enqueue_sync(self, account_id, kind):
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as db:
            account = self._lock(db, account_id)
            if account["status"] != "active" or self._profile(db, account_id)["archived_at"]:
                raise ApplicationError("Provider account is not connected", 409, "provider_disconnected")
            existing = db.execute(text("SELECT * FROM provider_sync_jobs WHERE account_id=:id AND kind=:kind"), {"id": account_id, "kind": kind}).mappings().first()
            if existing and existing["status"] in {"pending", "running"}:
                return dict(existing)
            job_id = existing["id"] if existing else uuid.uuid4().hex
            if existing:
                db.execute(text("DELETE FROM provider_sync_jobs WHERE id=:id"), {"id": job_id})
            values = {"id": job_id, "account_id": account_id, "kind": kind, "now": now}
            db.execute(text("""INSERT INTO provider_sync_jobs (id,account_id,kind,status,attempts,available_at,created_at,updated_at)
                VALUES (:id,:account_id,:kind,'pending',0,:now,:now,:now)"""), values)
            return {"id": job_id, "account_id": account_id, "kind": kind, "status": "pending"}

    def schedule_sync(self):
        now = datetime.now(UTC)
        with self.engine.connect() as db:
            rows = [dict(row) for row in db.execute(text("""SELECT s.* FROM provider_sync_settings s
                JOIN provider_accounts a ON a.id=s.account_id
                LEFT JOIN provider_account_profiles p ON p.account_id=a.id
                WHERE s.enabled=1 AND a.status='active' AND COALESCE(p.enabled,1)=1 AND p.archived_at IS NULL
                AND (s.next_quota_at<=:now OR s.next_models_at<=:now)"""), {"now": now.isoformat()}).mappings()]
        for row in rows:
            for kind in ("quota", "models"):
                if row[f"next_{kind}_at"] <= now.isoformat():
                    self.enqueue_sync(row["account_id"], kind)
                    with self.engine.begin() as db:
                        db.execute(text(f"UPDATE provider_sync_settings SET next_{kind}_at=:next WHERE account_id=:id AND next_{kind}_at<=:now"), {"id": row["account_id"], "now": now.isoformat(), "next": (now + timedelta(seconds=row[f"{kind}_interval"])).isoformat()})

    def claim_sync(self, owner, lease_seconds=180):
        now = datetime.now(UTC)
        with self.engine.begin() as db:
            db.execute(text("""UPDATE provider_sync_jobs SET status='failed',error_code='worker_lease_expired',
                lease_owner=NULL,lease_until=NULL,updated_at=:now WHERE attempts>=3 AND
                ((status='running' AND lease_until<=:now) OR (status='pending' AND available_at<=:now))"""), {"now": now.isoformat()})
            suffix = " FOR UPDATE SKIP LOCKED" if db.engine.dialect.name == "mysql" else ""
            row = db.execute(text("""SELECT * FROM provider_sync_jobs WHERE
                (status='pending' AND available_at<=:now) OR (status='running' AND lease_until<=:now)
                ORDER BY available_at,id LIMIT 1""" + suffix), {"now": now.isoformat()}).mappings().first()
            if row is None:
                return None
            updated = db.execute(text("""UPDATE provider_sync_jobs SET status='running',attempts=attempts+1,
                lease_owner=:owner,lease_until=:until,updated_at=:now WHERE id=:id AND
                ((status='pending' AND available_at<=:now) OR (status='running' AND lease_until<=:now))"""), {"id": row["id"], "owner": owner, "now": now.isoformat(), "until": (now + timedelta(seconds=lease_seconds)).isoformat()})
            return {**dict(row), "attempts": row["attempts"] + 1, "lease_owner": owner} if updated.rowcount == 1 else None

    def finish_sync(self, job, error=None, retry=False):
        now = datetime.now(UTC)
        pending = bool(error and retry and job["attempts"] < 3)
        with self.engine.begin() as db:
            return db.execute(text("""UPDATE provider_sync_jobs SET status=:status,error_code=:error,
                available_at=:available,lease_owner=NULL,lease_until=NULL,updated_at=:now
                WHERE id=:id AND status='running' AND lease_owner=:owner AND attempts=:attempts AND lease_until>:now"""), {
                "id": job["id"], "owner": job["lease_owner"], "attempts": job["attempts"], "error": error,
                "status": "pending" if pending else "failed" if error else "succeeded", "now": now.isoformat(),
                "available": (now + timedelta(seconds=2 ** job["attempts"])).isoformat(),
            }).rowcount == 1

    def abandon_sync(self, owner):
        with self.engine.begin() as db:
            db.execute(text("""UPDATE provider_sync_jobs SET status='pending',lease_owner=NULL,lease_until=NULL,
                available_at=:now,updated_at=:now WHERE status='running' AND lease_owner=:owner"""), {"owner": owner, "now": datetime.now(UTC).isoformat()})
