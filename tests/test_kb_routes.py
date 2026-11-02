from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import routes
from app.types.auth import AuthContext


class RecordingKbService:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            if name in {"ask", "deep_research", "search"}:
                assert kwargs["auth_context"].principal_id == "admin-1"
            self.calls.append((name, args))
            if name == "list_kbs":
                return []
            return {"operation": name}

        return call


def make_client(monkeypatch):
    service = RecordingKbService()
    container = SimpleNamespace(kb_service=service)
    monkeypatch.setattr(routes, "get_container", lambda: container)
    app = FastAPI()
    app.include_router(routes.kb_router)

    @app.middleware("http")
    async def add_admin_context(request, call_next):
        request.state.auth_context = AuthContext("admin", "admin-1", "operator")
        return await call_next(request)

    return TestClient(app), service


def test_kb_routes_dispatch_document_search_task_index_and_source_operations(monkeypatch):
    client, service = make_client(monkeypatch)
    base = "/api/v1/kb/kb-1"

    assert client.post("/api/v1/kb", json={"name": "Manual"}).status_code == 200
    client.get("/api/v1/kb")
    client.get(base)
    client.put(base, json={"name": "Updated"})
    client.delete(base)
    client.post(f"{base}/documents", json={"filename": "guide.txt", "content": "hello"})
    upload = client.post(
        f"{base}/documents/upload",
        files={"file": ("guide.txt", b"hello world", "text/plain")},
        data={"file_type": "md", "source_type": "upload"},
    )
    assert upload.status_code == 200
    client.get(f"{base}/documents")
    client.delete(f"{base}/documents/doc-1")
    client.post(f"{base}/ask", json={"question": "where?"})
    client.post(f"{base}/deep-research", json={"question": "why?"})
    client.get(f"{base}/conversations")
    client.delete(f"{base}/conversations")
    client.get(f"{base}/tasks/task-1")
    client.post(f"{base}/tasks/task-1/cancel")
    client.get(f"{base}/tags?limit=4")
    client.post(f"{base}/tags/refresh?limit=6")
    client.post(f"{base}/search", json={"query": "text", "top_k": 8})
    client.get(f"{base}/stats")
    client.post(f"{base}/documents/doc-1/reindex")
    client.get(f"{base}/documents/doc-1")
    client.get(f"{base}/index")
    client.post(f"{base}/index")
    client.delete(f"{base}/index")
    client.get(f"{base}/sources")
    client.post(f"{base}/sources", json={"source_type": "local_dir", "dir_path": "docs"})
    client.delete(f"{base}/sources/source-1")

    calls = {name: args for name, args in service.calls}
    assert len(service.calls) == 27
    assert calls["ask"][0] == "kb-1" and calls["ask"][1].kb_id == "kb-1"
    assert calls["deep_research"][0] == "kb-1" and calls["deep_research"][1].kb_id == "kb-1"
    assert calls["search"][0] == "kb-1" and calls["search"][1].kb_id == "kb-1"
    uploaded = calls["upload_doc"][1]
    assert uploaded.filename == "guide.txt"
    assert uploaded.file_type == "md" and uploaded.source_type == "upload"
    import base64

    assert base64.b64decode(uploaded.content) == b"hello world"
    assert calls["get_task"] == ("kb-1", "task-1")
    assert calls["get_tags"] == ("kb-1", 4)
    assert calls["refresh_tags"] == ("kb-1", 6)
    assert calls["create_source"] == ("kb-1", {"source_type": "local_dir", "dir_path": "docs"})


def test_kb_multipart_upload_rejects_missing_file(monkeypatch):
    client, service = make_client(monkeypatch)

    response = client.post(
        "/api/v1/kb/kb-1/documents/upload",
        data={"source_type": "upload"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "file is required"
    assert service.calls == []
