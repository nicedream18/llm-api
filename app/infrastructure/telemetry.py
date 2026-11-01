"""Optional OTLP spans; credentials, URLs, request and response bodies are excluded."""

import os
from urllib.parse import urlparse


def configure_tracing(app):
    endpoint = os.getenv("WALIAPI_OTLP_ENDPOINT", "")
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("WALIAPI_OTLP_ENDPOINT must be an HTTP endpoint without credentials or query")
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        raise RuntimeError("Install requirements-observability.txt to enable tracing") from None
    provider = TracerProvider(resource=Resource.create({"service.name": "waliapi"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)))
    tracer = provider.get_tracer("waliapi.http")

    @app.middleware("http")
    async def traced_request(request, call_next):
        # Auto-instrumentation could capture callback query strings or exception messages.
        with tracer.start_as_current_span("http.request", record_exception=False, set_status_on_exception=False) as span:
            response = await call_next(request)
            route = getattr(request.scope.get("route"), "path", "unmatched")
            span.set_attribute("http.route", route)
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("http.response.status_code", response.status_code)
            return response

    app.state.telemetry_provider = provider
    return provider
