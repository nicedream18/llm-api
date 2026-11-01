"""Admin local-management routes validate inputs and delegate off the event loop."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import platform_routes


def test_local_routes_preview_apply_restore_and_service(monkeypatch):
    calls = []
    class Config:
        def detect(self): calls.append(("detect",)); return [{"target": "codex"}]
        def preview(self, *args): calls.append(("preview", args)); return {"expected_sha256": "hash"}
        def apply(self, *args): calls.append(("apply", args)); return {"backup_id": "backup"}
        def restore(self, *args): calls.append(("restore", args)); return {"restored": True}
    class Service:
        def status(self): calls.append(("status",)); return {"process_running": False}
        def start(self, port): calls.append(("start", port)); return {"started": True}
        def stop(self): calls.append(("stop",)); return {"stopped": True}
    monkeypatch.setattr(platform_routes, "_local_manager", lambda _home: Config())
    monkeypatch.setattr(platform_routes, "ManagedService", lambda _state=None: Service())
    app = FastAPI(); app.include_router(platform_routes.router); client = TestClient(app)
    assert client.post("/api/v1/platform/local/config/detect").json()["data"]
    assert client.post("/api/v1/platform/local/config/preview", json={"target": "codex"}).status_code == 200
    assert client.post("/api/v1/platform/local/config/apply", json={"target": "codex"}).status_code == 422
    assert client.post("/api/v1/platform/local/config/apply", json={"target": "codex", "expected_sha256": "hash"}).status_code == 200
    assert client.post("/api/v1/platform/local/config/restore", json={"target": "codex"}).status_code == 422
    assert client.post("/api/v1/platform/local/config/restore", json={"target": "codex", "backup_id": "backup"}).status_code == 200
    assert client.get("/api/v1/platform/local/service").json()["data"]["process_running"] is False
    assert client.post("/api/v1/platform/local/service/start", json={"port": 9910}).status_code == 200
    assert client.post("/api/v1/platform/local/service/stop").status_code == 200
    assert [name for name, *_ in calls] == ["detect", "preview", "apply", "restore", "status", "start", "stop"]
