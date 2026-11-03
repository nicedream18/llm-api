"""Opaque sessions and login admission shared by every server process."""

import hashlib
import secrets
import time
import uuid

from sqlalchemy import text

from app.application.services.auth_service import AuthError
from app.infrastructure.database.connection import engine as default_engine


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AdminSessionRepository:
    def __init__(self, engine=None):
        self.engine = engine if engine is not None else default_engine

    def admit_login(self, client_ip):
        now = int(time.time())
        values = {"id": digest(client_ip or "unknown"), "now": now}
        with self.engine.begin() as db:
            insert = "INSERT IGNORE" if self.engine.dialect.name == "mysql" else "INSERT OR IGNORE"
            db.execute(text(insert + " INTO admin_login_windows (subject_hash,window_start,attempts) VALUES (:id,:now,0)"), values)
            suffix = " FOR UPDATE" if self.engine.dialect.name == "mysql" else ""
            row = db.execute(text("SELECT * FROM admin_login_windows WHERE subject_hash=:id" + suffix), values).mappings().one()
            attempts = 0 if row["window_start"] <= now - 60 else row["attempts"]
            if attempts >= 5:
                raise AuthError("Invalid credentials")
            db.execute(text("UPDATE admin_login_windows SET attempts=:attempts,window_start=:start WHERE subject_hash=:id"),
                       {**values, "attempts": attempts + 1, "start": now if attempts == 0 else row["window_start"]})
            db.execute(text("DELETE FROM admin_login_windows WHERE window_start<:before"), {"before": now - 86400})

    def login(self, username, validate, ttl):
        now = int(time.time())
        token = secrets.token_urlsafe(48)
        with self.engine.begin() as db:
            suffix = " FOR UPDATE" if self.engine.dialect.name == "mysql" else ""
            user = db.execute(text("SELECT * FROM admin_users WHERE username=:username" + suffix), {"username": username}).mappings().first()
            if not validate(user):
                raise AuthError("Invalid credentials")
            db.execute(text("DELETE FROM admin_sessions WHERE expires_at<=:now OR revoked_at IS NOT NULL"), {"now": now})
            count = db.execute(text("SELECT COUNT(*) FROM admin_sessions WHERE username=:username"), {"username": username}).scalar()
            if count >= 100:
                raise AuthError("Too many active sessions", 429, "session_limit")
            db.execute(text("""INSERT INTO admin_sessions (id,token_hash,username,credential_hash,created_at,expires_at)
                VALUES (:id,:token_hash,:username,:credential_hash,:now,:expires)"""),
                       {"id": uuid.uuid4().hex, "token_hash": digest(token), "username": username,
                        "credential_hash": digest(user["password_hash"]), "now": now, "expires": now + ttl})
        return token

    def verify(self, token):
        if not token or len(token) > 512:
            return None
        username_join = "s.username = u.username"
        if self.engine.dialect.name == "mysql":
            # Existing admin tables can use a different utf8mb4 collation
            # from migration-created sessions; make the comparison explicit.
            username_join = "s.username COLLATE utf8mb4_unicode_ci = u.username COLLATE utf8mb4_unicode_ci"
        with self.engine.connect() as db:
            row = db.execute(text(f"""SELECT s.username,s.credential_hash,u.password_hash,u.status FROM admin_sessions s
                JOIN admin_users u ON {username_join} WHERE s.token_hash=:hash
                AND s.revoked_at IS NULL AND s.expires_at>:now"""), {"hash": digest(token), "now": int(time.time())}).mappings().first()
            return row["username"] if row and row["status"] == 1 and secrets.compare_digest(row["credential_hash"], digest(row["password_hash"])) else None

    def revoke_token(self, token):
        if token:
            with self.engine.begin() as db:
                db.execute(text("UPDATE admin_sessions SET revoked_at=:now WHERE token_hash=:hash AND revoked_at IS NULL"), {"hash": digest(token), "now": int(time.time())})

    def revoke(self, username, session_id):
        with self.engine.begin() as db:
            return db.execute(text("UPDATE admin_sessions SET revoked_at=:now WHERE username=:username AND id=:id AND revoked_at IS NULL"),
                              {"username": username, "id": session_id, "now": int(time.time())}).rowcount > 0

    def sessions(self, username):
        with self.engine.connect() as db:
            return [dict(row) for row in db.execute(text("""SELECT id,created_at,expires_at,revoked_at FROM admin_sessions
                WHERE username=:username AND expires_at>:now ORDER BY created_at DESC LIMIT 100"""), {"username": username, "now": int(time.time())}).mappings()]
