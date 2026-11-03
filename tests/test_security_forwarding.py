import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from app.application.services.misc_services import ProxyService
from app.config import SecuritySettings
from app.domain.entities import ChannelEntity, DispatchResult, SecurityCustomRuleEntity
from app.domain.gateway import GatewayService
from app.domain.multipart import multipart_files, multipart_text_parts
from app.domain.security import SecurityScanner
from app.domain.security_policy import SecuritySnapshot

SECRET = "AKIAABCDEFGHIJKLMNOP"


class PolicyRepository:
    def __init__(self, settings=None, custom=()):
        self.value = SecuritySnapshot(settings or SecuritySettings(redact_secrets=True), tuple(custom))
        self.reads = 0
        self.findings = []

    def snapshot(self):
        self.reads += 1
        return self.value

    def save_findings(self, findings):
        self.findings.extend(findings)


class Logs:
    def __init__(self):
        self.rows = []

    def insert_log(self, row):
        self.rows.append(row)

    def insert_attempt(self, *args):
        pass


def harness(policy=None, response_secret=False):
    policy = policy or PolicyRepository()
    channel = ChannelEntity(id="echo", name="Echo", base_url="https://echo.test", models=["demo"])
    dispatcher = SimpleNamespace(candidates=lambda *args: [DispatchResult(channel, "demo")])
    gateway = GatewayService(dispatcher, None)
    asyncio.run(gateway.aclose())
    captured = []

    async def upstream(request):
        captured.append((request.url.path, await request.aread(), dict(request.headers)))
        if request.headers.get("content-type", "").startswith("application/json") and json.loads(request.content).get("stream"):
            return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "answer", "choices": [{"message": {"content": SECRET if response_secret else "ok"}, "finish_reason": "stop"}]})

    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    logs = Logs()
    return ProxyService(gateway, SecurityScanner(), SecuritySettings(), logs, policy), gateway, policy, captured, logs


@pytest.mark.parametrize("endpoint,fields", [
    ("/v1/chat/completions", {"messages": [{"role": "user", "content": SECRET}]}),
    ("/v1/messages", {"messages": [{"role": "user", "content": SECRET}], "max_tokens": 10}),
    ("/v1/responses", {"input": SECRET}),
    ("/v1/completions", {"prompt": SECRET}),
])
def test_actual_upstream_json_contains_only_redacted_credentials(endpoint, fields):
    proxy, gateway, policy, captured, logs = harness()
    try:
        status, _ = proxy.forward(json.dumps({"model": "demo", **fields}), {}, endpoint=endpoint)
        assert status == 200 and len(captured) == 1
        assert SECRET.encode() not in captured[0][1] and b"[REDACTED]" in captured[0][1]
        assert policy.reads == 1
        assert SECRET not in logs.rows[0].request_body and logs.rows[0].sanitized
    finally:
        asyncio.run(gateway.aclose())


@pytest.mark.parametrize("endpoint,fields", [
    ("/v1/chat/completions", {"messages": [{"role": "user", "content": SECRET}]}),
    ("/v1/messages", {"messages": [{"role": "user", "content": SECRET}], "max_tokens": 10}),
    ("/v1/responses", {"input": SECRET}),
    ("/v1/completions", {"prompt": SECRET}),
])
@pytest.mark.asyncio
async def test_streaming_request_redaction_reaches_actual_transport(endpoint, fields):
    # Constructing the harness uses asyncio.run for initial client cleanup.
    proxy, gateway, policy, captured, _ = await asyncio.to_thread(harness)
    try:
        frames = [frame async for frame in proxy.forward_stream_async(json.dumps({"model": "demo", "stream": True, **fields}), {}, endpoint=endpoint)]
        assert frames and captured
        assert SECRET.encode() not in captured[0][1] and b"[REDACTED]" in captured[0][1]
        assert policy.reads == 1
    finally:
        await gateway.aclose()


def test_multipart_duplicate_texts_rewritten_and_file_bytes_preserved():
    boundary = "security-boundary"
    pieces = []
    for name, value in [("model", "demo"), ("prompt", SECRET), ("prompt", "Bearer plain-token"), ("password", "x")]:
        pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    file_bytes = b"\x00\xff" + SECRET.encode() + b"\r\nfile-data"
    pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + file_bytes + b"\r\n")
    payload = b"".join(pieces) + f"--{boundary}--\r\n".encode()
    content_type = f"multipart/form-data; boundary={boundary}"
    proxy, gateway, _policy, captured, _ = harness()
    try:
        status, _ = proxy.forward(payload, {}, endpoint="/v1/audio/transcriptions", content_type=content_type)
        assert status == 200
        forwarded = captured[0][1]
        assert multipart_files(content_type, forwarded)["file"][2] == file_bytes
        assert [(p.name, p.value) for p in multipart_text_parts(content_type, forwarded)] == [("model", "demo"), ("prompt", "[REDACTED]"), ("prompt", "[REDACTED]"), ("password", "[REDACTED]")]
        assert captured[0][2]["content-type"] == content_type
    finally:
        asyncio.run(gateway.aclose())


def test_original_fields_are_scanned_before_lossy_protocol_conversion_and_block_logs_are_safe():
    rule = SecurityCustomRuleEntity(id="deny", category="keyword", pattern="internal-private", action="block")
    proxy, gateway, policy, captured, logs = harness(PolicyRepository(custom=[rule]))
    try:
        status, _ = proxy.forward(json.dumps({"model": "demo", "input": "hello", "extra": "internal-private", "password": SECRET}), {}, endpoint="/v1/responses")
        assert status == 403 and captured == []
        assert SECRET not in logs.rows[0].request_body and policy.findings
    finally:
        asyncio.run(gateway.aclose())


def test_response_uses_same_snapshot_and_log_marks_response_redaction():
    policy = PolicyRepository(SecuritySettings(redact_secrets=True, scan_response=True))
    proxy, gateway, _, _captured, logs = harness(policy, response_secret=True)
    try:
        # A policy change during forwarding must only affect the next request.
        original_scan = proxy.scanner.scan
        def scan(*args, **kwargs):
            policy.value = SecuritySnapshot(replace(policy.value.settings, enabled=False))
            return original_scan(*args, **kwargs)
        proxy.scanner.scan = scan
        status, result = proxy.forward('{"model":"demo","messages":[]}', {})
        assert status == 200 and SECRET not in json.dumps(result)
        assert policy.reads == 1 and logs.rows[0].sanitized
    finally:
        asyncio.run(gateway.aclose())


@pytest.mark.asyncio
async def test_policy_failure_and_stream_response_limit_do_not_contact_upstream():
    proxy, gateway, policy, captured, _ = await asyncio.to_thread(harness, PolicyRepository(SecuritySettings(scan_response=True)))
    try:
        frames = [x async for x in proxy.forward_stream_async('{"model":"demo","stream":true}', {})]
        assert "stream_response_policy_unsupported" in "".join(frames) and not captured
        def fail():
            raise RuntimeError("database down")
        policy.snapshot = fail
        status, _ = await asyncio.to_thread(proxy.forward, '{"model":"demo"}', {})
        assert status == 503 and not captured
        frames = [x async for x in proxy.forward_stream_async('{"model":"demo"}', {})]
        assert "security_scan_failed" in "".join(frames) and not captured
    finally:
        await gateway.aclose()
