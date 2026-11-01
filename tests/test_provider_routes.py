from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import provider_routes


class RecordingProviderService:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            return {"operation": name}

        return call


def test_provider_routes_cover_account_authorization_and_query_operations(monkeypatch):
    service = RecordingProviderService()
    monkeypatch.setattr(
        provider_routes,
        "get_container",
        lambda: type("Container", (), {"provider_service": service})(),
    )
    app = FastAPI()
    app.include_router(provider_routes.router)
    client = TestClient(app)

    assert client.get("/api/v1/providers").json()["data"]["operation"] == "list_accounts"
    client.post("/api/v1/providers", json={
        "provider": "codex", "name": "work", "model_mapping": {"chat": "upstream-chat"},
    })
    client.put("/api/v1/providers/account-1", json={
        "provider": "gemini", "name": "personal", "priority": 2,
    })
    client.post("/api/v1/providers/account-1/token", json={
        "access_token": "access", "refresh_token": "refresh", "expires_at": "2026-12-01T00:00:00Z",
    })
    client.post("/api/v1/providers/account-1/authorize")
    client.post("/api/v1/providers/callback/codex?state=state-012345678901&code=oauth-code")
    client.post("/api/v1/providers/account-1/refresh")
    client.post("/api/v1/providers/account-1/logout")
    client.get("/api/v1/providers/account-1/quota")
    client.get("/api/v1/providers/account-1/models")
    client.delete("/api/v1/providers/account-1")

    assert [call[0] for call in service.calls] == [
        "list_accounts", "create_account", "update_account", "set_token",
        "authorize", "callback", "refresh", "sign_out", "quota", "models",
        "delete_account",
    ]
    assert service.calls[3][1][0] == "account-1"
    assert service.calls[5][1] == ("state-012345678901", "oauth-code", ("admin", "system"), "codex", None)


def test_provider_routes_reject_invalid_account_input_before_dispatch(monkeypatch):
    service = RecordingProviderService()
    monkeypatch.setattr(
        provider_routes,
        "get_container",
        lambda: type("Container", (), {"provider_service": service})(),
    )
    app = FastAPI()
    app.include_router(provider_routes.router)
    client = TestClient(app)

    invalid_provider = client.post("/api/v1/providers", json={
        "provider": "unknown", "name": "bad",
    })
    missing_token = client.post("/api/v1/providers/a/token", json={"access_token": ""})

    assert invalid_provider.status_code == missing_token.status_code == 422
    assert service.calls == []
