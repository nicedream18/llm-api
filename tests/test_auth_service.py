from datetime import UTC

from app.application.services.auth_service import (
    AdminAuthService,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    encoded = hash_password('correct horse battery staple')
    assert verify_password('correct horse battery staple', encoded)
    assert not verify_password('wrong', encoded)

def test_session_roundtrip(monkeypatch):
    from dataclasses import replace

    import app.application.services.auth_service as auth_module
    monkeypatch.setattr(auth_module, 'config', replace(auth_module.config, auth=replace(auth_module.config.auth, session_secret='test-secret')))
    service = AdminAuthService()
    token = service.create_session('root')
    assert service.verify_session(token).principal_name == 'root'
    assert service.verify_session(token + 'x') is None

def test_api_key_expiration_and_permissions():
    from datetime import datetime, timedelta

    import pytest

    from app.application.services.auth_service import ApiKeyAuthorizer, AuthError
    from app.domain.entities import ApiKeyEntity

    class Repo:
        def __init__(self, entity):
            self.entity = entity
        def get_api_key_by_key(self, raw):
            return self.entity if raw == 'secret' else None

    entity = ApiKeyEntity(id='id-1', name='test', key='secret', status=1,
                          allowed_models=['allowed'], quota_limit=100,
                          expires_at=(datetime.now(UTC)+timedelta(hours=1)).isoformat())
    auth = ApiKeyAuthorizer(Repo(entity))
    context = auth.authenticate('secret')
    assert context.principal_id == 'id-1'
    with pytest.raises(AuthError) as err:
        auth.authorize_request(context, model='other')
    assert err.value.status_code == 403
    entity.expires_at = (datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    with pytest.raises(AuthError) as err:
        auth.authenticate('secret')
    assert err.value.status_code == 401


def test_admin_login_uses_repository_hash(monkeypatch):
    from dataclasses import replace

    import app.application.services.auth_service as auth_module
    from app.application.services.admin_service import AdminService

    monkeypatch.setattr(auth_module, 'config', replace(auth_module.config, auth=replace(
        auth_module.config.auth, admin_username='admin', session_secret='x' * 32)))

    class Repo:
        def get_user(self, username):
            return {'username': username, 'password_hash': hash_password('correct-password'), 'status': 1}
        def write_audit(self, *args, **kwargs):
            pass

    service = AdminService(Repo())
    token = service.login('admin', 'correct-password', '127.0.0.1', 'req-1')
    assert service.auth.verify_session(token).is_admin
