import base64
import hashlib
import hmac
from dataclasses import replace

import pytest

import app.application.services.auth_service as auth_module
from app.application.services.admin_service import AdminService
from app.application.services.auth_service import (
    AdminAuthService,
    ApiKeyAuthorizer,
    AuthError,
    fingerprint,
    hash_password,
    verify_password,
)
from app.domain.entities import ApiKeyEntity
from app.types.auth import AuthContext


def test_password_fallback_and_invalid_encoded_hash(monkeypatch):
    original_import = __import__

    def import_without_argon2(name, *args, **kwargs):
        if name == "argon2" or name.startswith("argon2."):
            raise ImportError("argon2 disabled for fallback test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", import_without_argon2)
    encoded = hash_password("fallback-password")
    assert encoded.startswith("pbkdf2_sha256$310000$")
    assert verify_password("fallback-password", encoded) is True
    assert verify_password("wrong-password", encoded) is False
    assert verify_password("", "") is False
    assert verify_password("password", "unsupported$scheme") is False
    assert verify_password("password", "pbkdf2_sha256$bad$salt$digest") is False
    assert fingerprint(None) is None
    assert fingerprint("secret") == hashlib.sha256(b"secret").hexdigest()[:16]


def test_admin_session_expiry_config_missing_rate_limit_and_admin_token(monkeypatch):
    monkeypatch.setattr(auth_module, "config", replace(
        auth_module.config,
        auth=replace(
            auth_module.config.auth,
            admin_username="root", admin_token="admin-token", admin_password_hash="hash",
            bootstrap_password="", session_secret="session-secret", session_ttl_seconds=10,
        ),
    ))
    now = [1000]
    monkeypatch.setattr(auth_module.time, "time", lambda: now[0])
    service = AdminAuthService()
    token = service.create_session("root")
    assert service.verify_session(token).principal_name == "root"
    now[0] = 1010
    assert service.verify_session(token) is None
    assert service.verify_session(None) is None
    assert service.verify_admin_token("admin-token").is_admin
    assert service.verify_admin_token("wrong") is None

    malformed_body = base64.urlsafe_b64encode(b"not-json").decode().rstrip("=")
    signature = hmac.new(b"session-secret", malformed_body.encode(), hashlib.sha256).digest()
    malformed_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    assert service.verify_session(f"{malformed_body}.{malformed_signature}") is None

    monkeypatch.setattr(auth_module, "verify_password", lambda *_args: False)
    for _ in range(5):
        with pytest.raises(AuthError, match="Invalid credentials"):
            service.login("root", "wrong", "192.0.2.4")
    with pytest.raises(AuthError, match="Invalid credentials"):
        service.login("root", "wrong", "192.0.2.4")

    monkeypatch.setattr(auth_module, "config", replace(
        auth_module.config,
        auth=replace(auth_module.config.auth, session_secret=""),
    ))
    no_session = AdminAuthService()
    with pytest.raises(AuthError, match="not configured"):
        no_session.create_session()
    assert no_session.verify_session("anything") is None


def test_api_key_auth_rejects_invalid_states_and_checks_channel_permissions():
    class Repository:
        entity = None

        def get_api_key_by_key(self, raw_key):
            return self.entity if raw_key == "client-key" else None

    repo = Repository()
    authorizer = ApiKeyAuthorizer(repo)
    with pytest.raises(AuthError, match="Missing"):
        authorizer.authenticate(None)
    with pytest.raises(AuthError, match="Invalid"):
        authorizer.authenticate("client-key")

    repo.entity = ApiKeyEntity(id="disabled", name="disabled", key="client-key", status=0)
    with pytest.raises(AuthError, match="Invalid"):
        authorizer.authenticate("client-key")
    repo.entity = ApiKeyEntity(
        id="enabled", name="client", key="client-key", status=1,
        allowed_models=["model-a"], allowed_channels=["channel-a"],
        quota_limit=20, quota_used=5,
    )
    context = authorizer.authenticate("client-key")
    assert context.quota_limit == 20 and context.quota_used == 5
    with pytest.raises(AuthError, match="Channel is not allowed"):
        authorizer.authorize_request(context, channel_id="channel-b")
    authorizer.authorize_request(context, model="model-a", channel_id="channel-a")
    authorizer.authorize_request(AuthContext("admin", "admin"), model="any", channel_id="any")

    repo.entity.expires_at = "not-a-date"
    with pytest.raises(AuthError, match="configuration is invalid"):
        authorizer.authenticate("client-key")


def test_admin_service_audits_password_change_success_and_failures(monkeypatch):
    class Repository:
        def __init__(self, change_result):
            self.change_result = change_result
            self.events = []

        def get_user(self, username):
            return {"username": username, "password_hash": "stub", "status": 1}

        def write_audit(self, *event):
            self.events.append(event)

        def change_password(self, username, password_hash):
            self.changed = (username, password_hash)
            return self.change_result

    monkeypatch.setattr(auth_module, "config", replace(
        auth_module.config,
        auth=replace(auth_module.config.auth, admin_username="root", session_secret="session-secret"),
    ))
    short_password_repo = Repository(True)
    short_service = AdminService(short_password_repo)
    with pytest.raises(AuthError, match="12 characters"):
        short_service.change_password("root", "short", None, None)

    missing_repo = Repository(False)
    with pytest.raises(AuthError, match="not found"):
        AdminService(missing_repo).change_password("root", "long-enough-password", "req-1", "127.0.0.1")
    assert missing_repo.events == []

    repo = Repository(True)
    service = AdminService(repo)
    service.change_password("root", "long-enough-password", "req-2", "127.0.0.1")
    assert repo.changed[0] == "root"
    assert repo.changed[1] != "long-enough-password"
    assert repo.events == [("root", "change_password", "req-2", "127.0.0.1", True)]
    service.audit("root", "custom", "req-3", None)
    assert repo.events[-1] == ("root", "custom", "req-3", None, True)

