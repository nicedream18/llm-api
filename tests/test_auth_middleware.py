from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.middleware.auth import (
    ApiKeyAuthMiddleware,
    _kb_api_key_read_allowed,
    _under,
)
from app.application.services.auth_service import AuthError
from app.types.auth import AuthContext


class FakeApiKeyAuthorizer:
    def authenticate(self, raw_key):
        if raw_key != "valid":
            raise AuthError("Invalid API key", 401, "authentication_error")
        return AuthContext("api_key", "key-id", "readonly")


async def endpoint(request: Request):
    context = getattr(request.state, "auth_context", None)
    return JSONResponse({"principal": context.principal_type if context else None})


@pytest.fixture
def protected_app(monkeypatch):
    container = SimpleNamespace(channel_repo=object())
    monkeypatch.setattr("app.api.middleware.auth.get_container", lambda: container)
    monkeypatch.setattr("app.api.middleware.auth.ApiKeyAuthorizer", lambda _repo: FakeApiKeyAuthorizer())
    app = Starlette(routes=[Route("/api/v1/kb/{kb_id}/ask", endpoint, methods=["POST"]),
                            Route("/api/v1/kb/{kb_id}", endpoint, methods=["DELETE"]),
                            Route("/api/v1/channels", endpoint, methods=["GET"])])
    app.add_middleware(ApiKeyAuthMiddleware)
    return app


def test_admin_path_matching_uses_segment_boundaries():
    assert _under("/api/v1/channels/123", "/api/v1/channels")
    assert not _under("/api/v1/channels-evil", "/api/v1/channels")


def test_data_plane_key_can_use_read_only_kb_post():
    assert _kb_api_key_read_allowed("POST", "/api/v1/kb/kb-1/ask", "/api/v1/kb")
    assert _kb_api_key_read_allowed("POST", "/api/v1/kb/kb-1/search", "/api/v1/kb")
    assert not _kb_api_key_read_allowed("POST", "/api/v1/kb/kb-1/documents", "/api/v1/kb")
    assert not _kb_api_key_read_allowed("DELETE", "/api/v1/kb/kb-1", "/api/v1/kb")


def test_api_key_cannot_modify_kb_but_can_ask(protected_app):
    client = TestClient(protected_app)
    denied = client.delete("/api/v1/kb/kb-1", headers={"Authorization": "Bearer valid"})
    allowed = client.post("/api/v1/kb/kb-1/ask", headers={"Authorization": "Bearer valid"})
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["principal"] == "api_key"


def test_admin_routes_require_authentication(protected_app):
    response = TestClient(protected_app).get("/api/v1/channels", headers={"X-Request-ID": "req-test-1"})
    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "req-test-1"
