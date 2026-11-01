"""Provider encryption key rollover with bounded previous-key readers."""

import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet


def provider_cipher(auth):
    seed = auth.provider_token_key or auth.session_secret or "development-only-provider-key"
    seeds = [seed, *auth.provider_token_previous_keys]
    return MultiFernet([Fernet(base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())) for value in seeds])


def rotate_provider_storage(repository, cipher):
    """Re-encrypt under account locks; any invalid ciphertext rolls back the batch."""
    from sqlalchemy import text

    count = 0
    with repository.engine.begin() as db:
        ids = list(db.execute(text("SELECT id FROM provider_accounts ORDER BY id")).scalars())
        for account_id in ids:
            repository._lock(db, account_id)
            rows = db.execute(text("SELECT id,access_token,refresh_token FROM provider_tokens WHERE account_id=:id"), {"id": account_id}).mappings().all()
            for row in rows:
                values = {name: cipher.rotate(row[name].encode()).decode() if row[name] else None for name in ("access_token", "refresh_token")}
                db.execute(text("UPDATE provider_tokens SET access_token=:access_token,refresh_token=:refresh_token WHERE id=:id"), {"id": row["id"], **values})
                count += 1
            states = db.execute(text("SELECT state_hash,verifier FROM provider_oauth_states WHERE account_id=:id"), {"id": account_id}).mappings().all()
            for state in states:
                db.execute(text("UPDATE provider_oauth_states SET verifier=:verifier WHERE state_hash=:hash"),
                           {"hash": state["state_hash"], "verifier": cipher.rotate(state["verifier"].encode()).decode()})
    return {"rotated_token_records": count, "account_count": len(ids)}
