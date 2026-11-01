"""Opt-in telemetry exports only safe route templates and status values."""

import builtins

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infrastructure.telemetry import configure_tracing


def test_tracing_disabled_invalid_and_missing_dependencies(monkeypatch):
    monkeypatch.delenv("WALIAPI_OTLP_ENDPOINT", raising=False)
    assert configure_tracing(FastAPI()) is None
    monkeypatch.setenv("WALIAPI_OTLP_ENDPOINT", "https://user:password@example.test/v1/traces")
    with pytest.raises(ValueError): configure_tracing(FastAPI())
    monkeypatch.setenv("WALIAPI_OTLP_ENDPOINT", "https://collector.example/v1/traces")
    original = builtins.__import__
    def without_sdk(name, *args, **kwargs):
        if name.startswith("opentelemetry.exporter"): raise ImportError("not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_sdk)
    with pytest.raises(RuntimeError, match="requirements-observability"):
        configure_tracing(FastAPI())


def test_traces_exclude_callback_credentials_and_exceptions(monkeypatch):
    pytest.importorskip("opentelemetry.sdk", reason="Optional observability SDK is not installed")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    exporter = InMemorySpanExporter()
    monkeypatch.setenv("WALIAPI_OTLP_ENDPOINT", "https://collector.example/v1/traces")
    monkeypatch.setattr("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", lambda **kwargs: exporter)
    app = FastAPI()
    @app.get("/callback/{provider}")
    def callback(provider: str): return {"provider": provider}
    @app.get("/failure")
    def failure(): raise RuntimeError("private-token")
    provider = configure_tracing(app)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/callback/vendor?code=private-code", headers={"Authorization": "Bearer private-token"}).status_code == 200
        assert client.get("/failure").status_code == 500
        provider.force_flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        assert spans[0].attributes["http.route"] == "/callback/{provider}"
        assert "private" not in str([(dict(span.attributes), span.events, span.status) for span in spans])
    finally:
        provider.shutdown()
