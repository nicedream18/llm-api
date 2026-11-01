from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import auth_routes
from app.application.services.auth_service import AuthError
from app.config import config
from app.types.auth import AuthContext


class RecordingAdminService:
    def logout(self, token):
        pass
    def __init__(self, fail_login=False):
        self.fail_login = fail_login
        self.calls = []

    def login(self, username, password, client_ip, request_id):
        self.calls.append(("login", username, password, client_ip, request_id))
        if self.fail_login:
            raise AuthError("Invalid credentials", 401)
        return "signed-session-token"

    def change_password(self, username, password, request_id, client_ip):
        self.calls.append(("change_password", username, password, request_id, client_ip))

    def audit(self, username, action, request_id, client_ip):
        self.calls.append(("audit", username, action, request_id, client_ip))


def make_client(monkeypatch, service):
    test_config = replace(
        config,
        auth=replace(
            config.auth,
            admin_username="test-admin",
            session_cookie_secure=False,
            session_ttl_seconds=600,
        ),
    )
    monkeypatch.setattr(auth_routes, "config", test_config)
    monkeypatch.setattr(
        auth_routes,
        "get_container",
        lambda: SimpleNamespace(admin_service=service),
    )
    app = FastAPI()
    app.include_router(auth_routes.router)

    @app.middleware("http")
    async def add_admin_context(request, call_next):
        request.state.auth_context = AuthContext("admin", "admin-1", "operator")
        return await call_next(request)

    return TestClient(app)


def test_admin_login_sets_http_only_session_cookie(monkeypatch):
    service = RecordingAdminService()
    client = make_client(monkeypatch, service)

    response = client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": "secret"}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"username": "test-admin"}
    cookie = response.cookies.get("waliapi_admin_session")
    assert cookie == "signed-session-token"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "max-age=600" in response.headers["set-cookie"].lower()
    assert service.calls[0][0:3] == ("login", "operator", "secret")


def test_admin_login_maps_auth_failure_and_rejects_invalid_payload(monkeypatch):
    service = RecordingAdminService(fail_login=True)
    client = make_client(monkeypatch, service)

    failed = client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": "bad"}
    )
    invalid = client.post("/api/v1/auth/login", json={"username": "", "password": ""})

    assert failed.status_code == 401 and failed.json()["code"] == "0008"
    assert invalid.status_code == 422
    assert len(service.calls) == 1


def test_admin_session_logout_and_password_change(monkeypatch):
    service = RecordingAdminService()
    client = make_client(monkeypatch, service)

    session = client.get("/api/v1/auth/session")
    logout = client.post("/api/v1/auth/logout")
    short_password = client.post(
        "/api/v1/auth/change-password", json={"password": "short"}
    )
    changed = client.post(
        "/api/v1/auth/change-password", json={"password": "long-enough-password"}
    )

    assert session.json()["data"] == {"authenticated": True, "username": "operator"}
    assert logout.status_code == 200 and 'waliapi_admin_session="";' in logout.headers["set-cookie"]
    assert short_password.status_code == 422
    assert changed.status_code == 200
    assert 'waliapi_admin_session="";' in changed.headers["set-cookie"]
    assert [call[0] for call in service.calls] == [
        "audit", "change_password",
    ]
    assert service.calls[0][1:3] == ("operator", "logout")
    assert service.calls[1][1:3] == ("operator", "long-enough-password")
