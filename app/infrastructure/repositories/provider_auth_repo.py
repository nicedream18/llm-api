"""Serialized credential changes and cross-worker OAuth/refresh transactions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.application.errors import ApplicationError
from app.domain.provider_adapters import config_hash


class ProviderAuthRepository:
    @staticmethod
    def _runtime(db, account_id):
        row = db.execute(text("SELECT * FROM provider_auth_runtime WHERE account_id=:id"), {"id": account_id}).mappings().first()
        if row:
            return dict(row)
        db.execute(text("INSERT INTO provider_auth_runtime (account_id,generation) VALUES (:id,0)"), {"id": account_id})
        return {"generation": 0, "refresh_owner": None, "refresh_until": None}

    def _invalidate_auth(self, db, account_id):
        self._runtime(db, account_id)
        db.execute(text("""UPDATE provider_auth_runtime SET generation=generation+1,
            refresh_owner=NULL,refresh_until=NULL WHERE account_id=:id"""), {"id": account_id})
        db.execute(text("DELETE FROM provider_oauth_states WHERE account_id=:id"), {"id": account_id})

    def store_token(self, account_id, values, expected_generation=None, owner=None):
        now = datetime.now(UTC).isoformat()
        with self.engine.begin() as db:
            self._lock(db, account_id)
            profile = self._profile(db, account_id)
            if profile["archived_at"]:
                raise ApplicationError("Provider account is archived", 409, "account_archived")
            runtime = self._runtime(db, account_id)
            if expected_generation is not None and runtime["generation"] != expected_generation:
                raise ApplicationError("Provider authorization changed; reconnect", 409, "authorization_changed")
            if owner is not None and (runtime["refresh_owner"] != owner or not runtime["refresh_until"] or runtime["refresh_until"] <= now):
                raise ApplicationError("Provider refresh lease expired", 409, "refresh_lease_expired")
            db.execute(text("DELETE FROM provider_tokens WHERE account_id=:id"), {"id": account_id})
            db.execute(text("""INSERT INTO provider_tokens
                (id,account_id,access_token,refresh_token,expires_at,created_at,updated_at)
                VALUES (:id,:account_id,:access_token,:refresh_token,:expires_at,:now,:now)"""), {
                "id": uuid.uuid4().hex, "account_id": account_id, "now": now, **values,
            })
            self._invalidate_auth(db, account_id)
            db.execute(text("UPDATE provider_accounts SET status='active',updated_at=:now WHERE id=:id"), {"id": account_id, "now": now})
            self._event(db, account_id, "token_updated", {})

    def invalidate_token(self, account_id):
        with self.engine.begin() as db:
            self._lock(db, account_id)
            self._invalidate_auth(db, account_id)
            db.execute(text("DELETE FROM provider_tokens WHERE account_id=:id"), {"id": account_id})
            db.execute(text("UPDATE provider_accounts SET status='signed_out',updated_at=:now WHERE id=:id"), {"id": account_id, "now": datetime.now(UTC).isoformat()})
            self._event(db, account_id, "signed_out", {})

    def store_oauth(self, values):
        with self.engine.begin() as db:
            account = self._lock(db, values["account_id"])
            if self._profile(db, values["account_id"])["archived_at"]:
                raise ApplicationError("Provider account is archived", 409, "account_archived")
            if account["provider"] != values["provider"] or config_hash(account) != values["config_hash"]:
                raise ApplicationError("Provider configuration changed", 409, "authorization_changed")
            generation = self._runtime(db, values["account_id"])["generation"]
            db.execute(text("DELETE FROM provider_oauth_states WHERE expires_at<=:now"), {"now": values["created_at"]})
            db.execute(text("""INSERT INTO provider_oauth_states
                (state_hash,account_id,provider,principal_type,principal_id,verifier,config_hash,generation,expires_at,created_at)
                VALUES (:state_hash,:account_id,:provider,:principal_type,:principal_id,:verifier,:config_hash,:generation,:expires_at,:created_at)"""), {**values, "generation": generation})
            self._event(db, values["account_id"], "authorization_started", {})

    def consume_oauth(self, state_hash, principal, provider=None):
        with self.engine.begin() as db:
            record = db.execute(text("SELECT * FROM provider_oauth_states WHERE state_hash=:hash"), {"hash": state_hash}).mappings().first()
            if record is None:
                return None
            account = self._lock(db, record["account_id"])
            now = datetime.now(UTC).isoformat()
            if (record["principal_type"], record["principal_id"]) != principal or (provider and record["provider"] != provider):
                raise ApplicationError("OAuth state does not belong to this request", 403, "oauth_subject_mismatch")
            deleted = db.execute(text("DELETE FROM provider_oauth_states WHERE state_hash=:hash"), {"hash": state_hash}).rowcount
            runtime = self._runtime(db, record["account_id"])
            if deleted != 1 or record["expires_at"] <= now or record["generation"] != runtime["generation"] or config_hash(account) != record["config_hash"]:
                return None
            return dict(record)

    def claim_refresh(self, account_id, owner, lease_seconds=150):
        now = datetime.now(UTC)
        with self.engine.begin() as db:
            self._lock(db, account_id)
            if self._profile(db, account_id)["archived_at"]:
                raise ApplicationError("Provider account is archived", 409, "account_archived")
            runtime = self._runtime(db, account_id)
            if runtime["refresh_owner"] and runtime["refresh_until"] > now.isoformat():
                raise ApplicationError("Provider token refresh is in progress", 409, "refresh_in_progress")
            token = db.execute(text("SELECT * FROM provider_tokens WHERE account_id=:id"), {"id": account_id}).mappings().first()
            if token is None:
                raise ApplicationError("Provider account is not connected", 404, "not_found")
            db.execute(text("UPDATE provider_auth_runtime SET refresh_owner=:owner,refresh_until=:until WHERE account_id=:id"), {"id": account_id, "owner": owner, "until": (now + timedelta(seconds=lease_seconds)).isoformat()})
            return {**dict(token), "generation": runtime["generation"]}

    def release_refresh(self, account_id, owner):
        with self.engine.begin() as db:
            db.execute(text("""UPDATE provider_auth_runtime SET refresh_owner=NULL,refresh_until=NULL
                WHERE account_id=:id AND refresh_owner=:owner"""), {"id": account_id, "owner": owner})
