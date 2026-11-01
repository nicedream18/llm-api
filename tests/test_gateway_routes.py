import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.controllers import routes
from app.application.services.misc_services import RawProxyResponse


class FakeProxyService:
    def __init__(self, result=None, status=200, chunks=None):
        self.result = result if result is not None else {"ok": True}
        self.status = status
        self.chunks = chunks or ["data: {\"ok\":true}\n\n"]
        self.calls = []

    def forward(self, body, headers, **options):
        self.calls.append(("forward", body, headers, options))
        return self.status, self.result

    async def forward_stream_async(self, body, headers, **options):
        self.calls.append(("stream", body, headers, options))
        for chunk in self.chunks:
            yield chunk


def make_client(monkeypatch, proxy):
    container = SimpleNamespace(proxy_service=proxy)
    monkeypatch.setattr(routes, "get_container", lambda: container)
    app = FastAPI()
    app.include_router(routes.gateway_router)
    return TestClient(app)


def test_chat_completion_route_forwards_json_and_returns_upstream_status(monkeypatch):
    proxy = FakeProxyService({"id": "response-1"}, status=201)
    client = make_client(monkeypatch, proxy)
    body = {"model": "model-a", "messages": [{"role": "user", "content": "hi"}]}

    response = client.post(
        "/v1/chat/completions", json=body, headers={"X-Test": "header"}
    )

    assert response.status_code == 201
    assert response.json() == {"id": "response-1"}
    call = proxy.calls[0]
    assert call[0] == "forward" and json.loads(call[1]) == body
    assert call[2]["x-test"] == "header"
    assert call[3]["endpoint"] == "/v1/chat/completions"
    assert call[3]["client_ip"] == "testclient"


def test_chat_completion_route_streams_sse_when_requested(monkeypatch):
    proxy = FakeProxyService(chunks=["data: first\n\n", "data: second\n\n"])
    client = make_client(monkeypatch, proxy)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "model-a", "stream": True},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "data: first\n\ndata: second\n\n"
    assert proxy.calls[0][0] == "stream"
    assert proxy.calls[0][3]["endpoint"] == "/v1/chat/completions"


def test_generic_route_preserves_multipart_bytes_and_content_type(monkeypatch):
    proxy = FakeProxyService({"text": "transcribed"})
    client = make_client(monkeypatch, proxy)
    payload = b"--boundary\r\ncontent\r\n--boundary--\r\n"
    content_type = "multipart/form-data; boundary=boundary"

    response = client.post(
        "/v1/audio/transcriptions", content=payload,
        headers={"Content-Type": content_type},
    )

    assert response.json() == {"text": "transcribed"}
    call = proxy.calls[0]
    assert call[1] == payload
    assert call[3]["content_type"] == content_type
    assert call[3]["endpoint"] == "/v1/audio/transcriptions"


def test_generic_route_preserves_raw_binary_upstream_response(monkeypatch):
    proxy = FakeProxyService(
        RawProxyResponse(
            content=b"\x00\x01audio",
            media_type="audio/mpeg",
            headers={"X-Upstream": "provider"},
        )
    )
    client = make_client(monkeypatch, proxy)

    response = client.post("/v1/audio/speech", json={"input": "hello"})

    assert response.status_code == 200
    assert response.content == b"\x00\x01audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["x-upstream"] == "provider"


def test_health_endpoint_reports_basic_service_identity():
    app = FastAPI()
    app.include_router(routes.gateway_router)

    response = TestClient(app).get("/health")

    assert response.json() == {
        "status": "ok", "service": "WaLiAPI-Python", "version": "1.0.0",
    }
