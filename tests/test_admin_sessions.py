"""Durable authentication, concurrent admission and management isolation."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.controllers import administration_routes, auth_routes
from app.api.middleware.auth import ApiKeyAuthMiddleware, RequestContextMiddleware
from app.application.services.admin_service import AdminService
from app.application.services.admin_sessions import DurableAdminAuth
from app.application.services.auth_service import AuthError, hash_password
from app.config import config
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.admin_session_repo import AdminSessionRepository
from app.infrastructure.token_keyring import provider_cipher, rotate_provider_storage


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "admin.db"), connect_args={"check_same_thread": False, "timeout": 10})
    with engine.begin() as db:
        db.execute(text("CREATE TABLE admin_users (id TEXT PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,status INTEGER)"))
        db.execute(text("CREATE TABLE admin_audit_logs (id TEXT,username TEXT,action TEXT,request_id TEXT,client_ip TEXT,success INTEGER,created_at TEXT)"))
        path = Path("docs/migrations/026_admin_sessions.sql")
        execute_migration(db, path)
        execute_migration(db, path)
        db.execute(text("INSERT INTO admin_users VALUES ('u','admin',:hash,1)"), {"hash": hash_password("correct-password")})
    yield AdminSessionRepository(engine)
    engine.dispose()


def test_sessions_survive_restart_revoke_and_password_change(sessions):
    service = DurableAdminAuth(None, sessions)
    token = service.login("admin", "correct-password", "127.0.0.1")
    restarted = DurableAdminAuth(None, AdminSessionRepository(sessions.engine))
    assert restarted.verify_session(token).is_admin
    assert not restarted.verify_session("legacy.signed-cookie")
    assert not restarted.verify_session("x" * 513)
    assert restarted.verify_session(None) is None
    with sessions.engine.connect() as db:
        assert token not in str(db.execute(text("SELECT * FROM admin_sessions")).all())
    row = sessions.sessions("admin")[0]
    assert not sessions.revoke("another-user", row["id"])
    assert sessions.revoke("admin", row["id"])
    assert not sessions.revoke("admin", row["id"])
    assert restarted.verify_session(token) is None
    token = service.login("admin", "correct-password", "127.0.0.1")
    with sessions.engine.begin() as db:
        db.execute(text("UPDATE admin_users SET password_hash=:hash"), {"hash": hash_password("changed-password")})
    assert restarted.verify_session(token) is None
    with pytest.raises(AuthError):
        service.login("admin", "correct-password", "another-ip")
    token = service.login("admin", "changed-password", "another-ip")
    sessions.revoke_token(token)
    sessions.revoke_token(None)
    assert service.verify_session(token) is None
    token = service.login("admin", "changed-password", "another-ip")
    with sessions.engine.begin() as db:
        db.execute(text("UPDATE admin_users SET status=0"))
    assert service.verify_session(token) is None
    with pytest.raises(AuthError):
        service.login("admin", "changed-password", "another-ip")
    with pytest.raises(AuthError):
        service.login("unknown", "changed-password", "unknown-ip")


def test_login_admission_is_cross_instance_atomic_and_expires(sessions, monkeypatch):
    def admit(_):
        try:
            AdminSessionRepository(sessions.engine).admit_login("shared-ip")
            return True
        except AuthError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(12))) == 5
    monkeypatch.setattr("app.infrastructure.repositories.admin_session_repo.time.time", lambda: time.monotonic() + 10_000_000_000)
    sessions.admit_login("shared-ip")
    with sessions.engine.connect() as db:
        assert db.execute(text("SELECT attempts FROM admin_login_windows")).scalar() == 1


def test_expiry_limit_and_transaction_rollback(sessions, monkeypatch):
    token = sessions.login("admin", lambda _: True, -1)
    assert sessions.verify(token) is None
    assert sessions.sessions("admin") == []
    with pytest.raises(RuntimeError):
        sessions.login("admin", lambda _: (_ for _ in ()).throw(RuntimeError("verification failed")), 60)
    with sessions.engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM admin_sessions")).scalar() == 1
    monkeypatch.setattr("app.infrastructure.repositories.admin_session_repo.secrets.token_urlsafe", lambda _: "constant")
    sessions.login("admin", lambda _: True, 60)
    with sessions.engine.begin() as db:
        for index in range(99):
            db.execute(text("INSERT INTO admin_sessions SELECT :id,:id,username,credential_hash,created_at,expires_at,NULL FROM admin_sessions LIMIT 1"), {"id": f"session{index}"})
        db.execute(text("UPDATE admin_sessions SET expires_at=:expires"), {"expires": int(time.time()) + 100})
    with pytest.raises(AuthError, match="Too many"):
        sessions.login("admin", lambda _: True, 60)


def test_real_http_login_logout_and_new_auth_routes_are_protected(sessions, monkeypatch):
    service = AdminService(SimpleNamespace(write_audit=lambda *args: None), sessions)
    container = SimpleNamespace(admin_service=service, channel_repo=None, admin_repo=SimpleNamespace(write_audit=lambda *args: None))
    monkeypatch.setattr(auth_routes, "get_container", lambda: container)
    monkeypatch.setattr("app.api.middleware.auth.get_container", lambda: container)
    app = FastAPI(); app.include_router(auth_routes.router)
    app.add_middleware(RequestContextMiddleware); app.add_middleware(ApiKeyAuthMiddleware)
    client = TestClient(app)
    assert client.get("/api/v1/auth/sessions").status_code == 401
    assert client.get("/api/v1/administration/metrics").status_code == 401
    result = client.post("/api/v1/auth/login", json={"username": "admin", "password": "correct-password"})
    assert result.status_code == 200
    token = result.cookies["waliapi_admin_session"]
    assert client.get("/api/v1/auth/sessions").json()["data"]
    assert client.delete("/api/v1/auth/sessions/missing").status_code == 404
    first_ids = {row["id"] for row in sessions.sessions("admin")}
    second = service.auth.login("admin", "correct-password", "separate-ip")
    second_id = next(row["id"] for row in sessions.sessions("admin") if row["id"] not in first_ids)
    # Revoke by an independent ID and ensure the token cannot be reused.
    assert client.delete("/api/v1/auth/sessions/" + second_id).status_code == 200
    assert service.auth.verify_session(second) is None
    assert client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert service.auth.verify_session(token)
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert service.auth.verify_session(token) is None
    assert client.delete("/api/v1/auth/sessions/missing").status_code == 401


def test_key_rollover_and_invalid_ciphertext_rollback(provider_database):
    service, account = provider_database
    old_auth = config.auth
    new_auth = replace(old_auth, provider_token_key="new-encryption-key", provider_token_previous_keys=(old_auth.provider_token_key or old_auth.session_secret or "development-only-provider-key",))
    keyring = provider_cipher(new_auth)
    original = service.repo.get_token(account)["access_token"]
    with service.repo.engine.begin() as db:
        db.execute(text("""INSERT INTO provider_oauth_states
            (state_hash,account_id,provider,principal_type,principal_id,verifier,config_hash,generation,expires_at,created_at)
            VALUES ('state',:account,'codex','admin','operator',:verifier,'hash',1,'later','now')"""), {"account": account, "verifier": service._encrypt("pkce-verifier")})
    assert keyring.decrypt(original.encode()).decode() == "synthetic-access"
    assert rotate_provider_storage(service.repo, keyring)["rotated_token_records"] == 1
    rotated = service.repo.get_token(account)["access_token"]
    with service.repo.engine.connect() as db:
        verifier = db.execute(text("SELECT verifier FROM provider_oauth_states")).scalar()
        assert provider_cipher(replace(new_auth, provider_token_previous_keys=())).decrypt(verifier.encode()) == b"pkce-verifier"
    assert rotated != original and provider_cipher(replace(new_auth, provider_token_previous_keys=())).decrypt(rotated.encode()) == b"synthetic-access"
    with pytest.raises(InvalidToken):
        provider_cipher(old_auth).decrypt(rotated.encode())
    with service.repo.engine.begin() as db:
        db.execute(text("UPDATE provider_tokens SET refresh_token='invalid'"))
    with pytest.raises(InvalidToken):
        rotate_provider_storage(service.repo, keyring)
    assert service.repo.get_token(account)["access_token"] == rotated


def test_keyring_configuration_validation(monkeypatch):
    from app.config import AuthConfig
    monkeypatch.setenv("PROVIDER_TOKEN_PREVIOUS_KEYS", '{}')
    with pytest.raises(TypeError, match="JSON array"): AuthConfig()
    monkeypatch.setenv("PROVIDER_TOKEN_PREVIOUS_KEYS", '["short"]')
    with pytest.raises(ValueError, match="previous keys"): AuthConfig()


def test_audit_diagnostics_and_metrics_are_bounded_and_do_not_expose_secrets(sessions, monkeypatch):
    monkeypatch.setattr(administration_routes, "engine", sessions.engine)
    monkeypatch.setattr(administration_routes, "status", lambda: [{"applied": True, "checksum_valid": True}])
    assert administration_routes.diagnostics_data()["migrations"] == "ok"
    monkeypatch.setattr(administration_routes, "status", lambda: [{"applied": False, "checksum_valid": True}])
    assert administration_routes.diagnostics_data()["migrations"] == "pending_or_invalid"
    with sessions.engine.begin() as db:
        db.execute(text("CREATE TABLE usage_ledger (kind TEXT)"))
        db.execute(text("INSERT INTO usage_ledger VALUES ('attempt'),('attempt'),('outcome'),('secret')"))
    assert 'kind="attempt"} 2' in administration_routes.metric_text()
    assert "secret" not in administration_routes.metric_text()
    assert administration_routes.audit_rows(10, 0, "") == []
    app = FastAPI(); app.include_router(administration_routes.router)
    client = TestClient(app)
    assert client.get("/api/v1/administration/audit?limit=1000").status_code == 422
    assert client.get("/api/v1/administration/audit").json()["data"] == []
    assert client.get("/api/v1/administration/metrics").headers["content-type"].startswith("text/plain")
    monkeypatch.setattr(administration_routes, "get_container", lambda: SimpleNamespace(gateway=SimpleNamespace(client=SimpleNamespace(is_closed=False)), kb_worker=SimpleNamespace(running=True), provider_sync_worker=SimpleNamespace(running=True), operations_worker=SimpleNamespace(task=None)))
    assert client.get("/api/v1/administration/diagnostics").json()["data"]["workers"]["knowledge"]
    monkeypatch.setattr(administration_routes, "status", lambda: (_ for _ in ()).throw(RuntimeError("private-connection-string")))
    assert administration_routes.diagnostics_data()["migrations"] == "unavailable"


@pytest.mark.asyncio
async def test_lifespan_releases_partial_start_and_continues_after_stop_failure(monkeypatch):
    from app import main
    calls = []
    class Worker:
        def __init__(self, name, fail=False): self.name, self.fail = name, fail
        async def start(self):
            calls.append("start:" + self.name)
            if self.fail: raise RuntimeError("failed start")
        async def stop(self):
            calls.append("stop:" + self.name)
            raise RuntimeError("failed stop")
    async def close(): calls.append("close")
    container = SimpleNamespace(kb_worker=Worker("kb"), provider_sync_worker=Worker("sync", True), operations_worker=Worker("ops"), gateway=SimpleNamespace(aclose=close))
    monkeypatch.setattr(main, "get_container", lambda: container)
    monkeypatch.setattr(main, "apply_migrations", lambda: None)
    with pytest.raises(RuntimeError, match="failed start"):
        async with main.lifespan(main.app): pass
    assert calls == ["start:kb", "start:sync", "stop:sync", "stop:kb", "close"]


def test_audit_records_started_success_rejection_and_exception(monkeypatch):
    events = []
    monkeypatch.setattr("app.api.middleware.auth.get_container", lambda: SimpleNamespace(admin_repo=SimpleNamespace(write_audit=lambda *args: events.append(args))))
    app = FastAPI()
    @app.post('/api/v1/write')
    def write(): return {"ok": True}
    @app.post('/api/v1/fail')
    def fail(): raise RuntimeError("synthetic-private-error")
    app.add_middleware(RequestContextMiddleware)
    @app.middleware('http')
    async def identify(request, call_next):
        from app.types.auth import AuthContext
        request.state.auth_context = AuthContext("admin", "admin", "admin")
        return await call_next(request)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post('/api/v1/write', json={"secret": "should-not-be-logged"}).status_code == 200
    assert client.post('/api/v1/fail').status_code == 500
    assert [row[-1] for row in events] == [True, True, True, False]
    assert "should-not-be-logged" not in str(events) and "synthetic-private-error" not in str(events)
