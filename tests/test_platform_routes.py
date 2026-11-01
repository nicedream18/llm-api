from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import platform_routes


class RecordingPlatformService:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            return {"operation": name}

        return call


def test_platform_routes_validate_and_dispatch_platform_operations(monkeypatch):
    service = RecordingPlatformService()
    monkeypatch.setattr(
        platform_routes,
        "get_container",
        lambda: type("Container", (), {"platform_service": service})(),
    )
    app = FastAPI()
    app.include_router(platform_routes.router)
    client = TestClient(app)

    assert client.get("/api/v1/platform/prompts").json()["data"]["operation"] == "list_prompts"
    assert client.post("/api/v1/platform/prompts", json={
        "name": "summary", "template": "Summarize {{text}}", "description": "short",
    }).status_code == 200
    client.put("/api/v1/platform/prompts/p-1", json={
        "name": "summary", "template": "Summarize {{text}}",
    })
    client.delete("/api/v1/platform/prompts/p-1")
    rendered = client.post("/api/v1/platform/prompts/p-1/render", json={
        "variables": {"text": "content"},
    })
    assert rendered.json()["data"]["operation"] == "render_prompt"

    client.post("/api/v1/platform/cache/get", json={
        "model": "model-a", "request": {"messages": []}, "scope": "team",
    })
    client.post("/api/v1/platform/cache/put", json={
        "model": "model-a", "request": {"messages": []},
        "response": {"text": "answer"}, "scope": "team", "ttl_seconds": 60,
    })
    client.delete("/api/v1/platform/cache")
    client.post("/api/v1/platform/config/preview", json={
        "target": "codex", "values": {"model": "model-a"},
    })
    client.get("/api/v1/platform/config")
    client.post("/api/v1/platform/config/write", json={
        "target": "codex", "values": {"model": "model-a"},
    })
    client.delete("/api/v1/platform/config/codex")

    assert [call[0] for call in service.calls] == [
        "list_prompts", "create_prompt", "update_prompt", "delete_prompt",
        "render_prompt", "cache_get", "cache_put", "clear_cache",
        "preview_config", "list_configs", "write_config", "delete_config",
    ]
    assert service.calls[4][1] == ("p-1", {"text": "content"})
    assert service.calls[6][1][-1] == 60


def test_platform_routes_reject_invalid_contracts_before_dispatch(monkeypatch):
    service = RecordingPlatformService()
    monkeypatch.setattr(
        platform_routes,
        "get_container",
        lambda: type("Container", (), {"platform_service": service})(),
    )
    app = FastAPI()
    app.include_router(platform_routes.router)
    client = TestClient(app)

    invalid_prompt = client.post("/api/v1/platform/prompts", json={
        "name": "", "template": "valid", "unknown": True,
    })
    invalid_target = client.post("/api/v1/platform/config/write", json={
        "target": "../outside", "values": {},
    })
    invalid_ttl = client.post("/api/v1/platform/cache/put", json={
        "model": "model-a", "request": {}, "response": {}, "ttl_seconds": 0,
    })

    assert invalid_prompt.status_code == invalid_target.status_code == invalid_ttl.status_code == 422
    assert service.calls == []
