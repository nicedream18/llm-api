import json
from types import SimpleNamespace

import pytest

from app.application.services.misc_services import ProxyService, RawProxyResponse
from app.domain.entities import ProxyResponseEntity, SecurityScanResult
from app.types.auth import AuthContext


class FakeLogRepository:
    def __init__(self):
        self.logs = []
        self.attempts = []

    def insert_log(self, entry):
        self.logs.append(entry)

    def insert_attempt(self, request_id, attempt):
        self.attempts.append((request_id, attempt))


class FakeSecurityScanner:
    def __init__(self, results=None, error=None):
        self.results = list(results or [])
        self.error = error
        self.calls = []

    def scan(self, body, phase, settings, custom_rules, builtin_rules):
        self.calls.append((body, phase, custom_rules, builtin_rules))
        if self.error:
            raise self.error
        return self.results.pop(0) if self.results else SecurityScanResult()


class FakeSecurityRepository:
    def get_all_custom_rules(self):
        return ["custom"]

    def get_all_builtin_rules(self):
        return ["builtin"]

    def save_findings(self, findings):
        self.findings = findings


class FakeQuotaRepository:
    def __init__(self, reservation="reservation-1"):
        self.reservation = reservation
        self.calls = []

    def reserve(self, key_id, request_id, tokens):
        self.calls.append(("reserve", key_id, request_id, tokens))
        return self.reservation

    def settle(self, reservation_id, tokens):
        self.calls.append(("settle", reservation_id, tokens))

    def release(self, reservation_id):
        self.calls.append(("release", reservation_id))


class FakeGateway:
    def __init__(self, response=None, error=None, stream_lines=None):
        self.response = response or ProxyResponseEntity(
            body=json.dumps({"id": "answer", "choices": [{"message": {"content": "ok"}}]}),
            prompt_tokens=2, completion_tokens=3, total_tokens=5,
        )
        self.error = error
        self.stream_lines = stream_lines or [
            'data: {"id":"chunk-1","choices":[{"delta":{"content":"ok"},"finish_reason":null}]}',
            "",
            'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}',
            "",
            "data: [DONE]",
            "",
        ]
        self.requests = []

    async def forward(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response

    async def stream(self, request, on_attempt=None):
        self.requests.append(request)
        if on_attempt:
            on_attempt({"attempt": 1, "status": 200})
        for line in self.stream_lines:
            yield line


def make_proxy(
    *, gateway=None, settings=None, scanner=None, log=None, security_repo=None,
    quota=None,
):
    log = log or FakeLogRepository()
    return ProxyService(
        gateway or FakeGateway(), scanner,
        settings or SimpleNamespace(enabled=False, scan_response=False, fail_closed=True),
        log, security_repo, quota,
    ), log


def test_forward_rejects_invalid_json_missing_model_and_forbidden_model():
    proxy, log = make_proxy()
    assert proxy.forward("not-json", {})[0] == 400
    assert proxy.forward("{}", {})[1]["error"]["code"] == "missing_model"

    context = AuthContext("api_key", "key-1", allowed_models=frozenset({"allowed"}))
    status, result = proxy.forward('{"model":"blocked"}', {}, auth_context=context)

    assert status == 403 and result["error"]["code"] == "model_forbidden"
    assert log.logs == []


def test_forward_blocks_scanned_request_and_persists_findings(monkeypatch):
    finding = SimpleNamespace(log_id=None)
    scan = SecurityScanResult(
        risk_level="Critical", risk_score=100, summary="blocked request",
        findings=[finding], blocked=True, blocked_reason="critical rule",
    )
    scanner = FakeSecurityScanner([scan])
    log = FakeLogRepository()
    security = FakeSecurityRepository()
    gateway = FakeGateway()
    settings = SimpleNamespace(enabled=True, scan_response=False, fail_closed=True)
    proxy = ProxyService(gateway, scanner, settings, log, security)

    status, result = proxy.forward('{"model":"model","messages":[]}', {}, request_id="req-1")

    assert status == 403 and result["error"]["code"] == "security_blocked"
    assert not gateway.requests
    assert log.logs[0].security_action == "Block"
    assert log.logs[0].blocked_reason == "critical rule"
    assert security.findings == [finding] and finding.log_id == log.logs[0].id


def test_forward_uses_sanitized_body_settles_quota_and_records_attempts():
    scan = SecurityScanResult(sanitized=True, sanitized_body='{"model":"model","safe":true}')
    scanner = FakeSecurityScanner([scan])
    log = FakeLogRepository()
    quota = FakeQuotaRepository()
    gateway = FakeGateway()
    settings = SimpleNamespace(enabled=True, scan_response=False, fail_closed=True)

    async def forward_with_attempts(request, on_attempt):
        attempt = {"attempt": 1}
        on_attempt(attempt)
        gateway.requests.append(request)
        return gateway.response, [attempt]

    gateway.forward_with_attempts = forward_with_attempts
    proxy = ProxyService(gateway, scanner, settings, log, FakeSecurityRepository(), quota)
    context = AuthContext("api_key", "key-1", "client", allowed_models=frozenset({"model"}))

    status, result = proxy.forward(
        '{"model":"model","secret":"redact"}', {}, auth_context=context,
        request_id="request-9", endpoint="/v1/chat/completions",
    )

    assert status == 200 and result["id"] == "answer"
    assert gateway.requests[0].body == {"model": "model", "safe": True}
    assert quota.calls[0][0:3] == ("reserve", "key-1", "request-9")
    assert quota.calls[-1] == ("settle", "reservation-1", 5)
    assert log.attempts == [("request-9", {"attempt": 1})]
    assert log.logs[0].request_body == '{"model":"model","safe":true}'
    assert log.logs[0].api_key_name == "client"
    assert log.logs[0].attempt_count == log.logs[0].final_attempt == 1


def test_forward_handles_quota_denial_gateway_errors_and_upstream_failures():
    context = AuthContext("api_key", "key-1", allowed_models=frozenset({"model"}))
    denied_quota = FakeQuotaRepository(reservation=None)
    proxy, _ = make_proxy(quota=denied_quota)
    status, result = proxy.forward('{"model":"model"}', {}, auth_context=context)
    assert status == 429 and result["error"]["code"] == "quota_exceeded"

    quota = FakeQuotaRepository()
    proxy, _ = make_proxy(gateway=FakeGateway(error=RuntimeError("gateway failure")), quota=quota)
    with pytest.raises(RuntimeError, match="gateway failure"):
        proxy.forward('{"model":"model"}', {}, auth_context=context)
    assert quota.calls[-1] == ("release", "reservation-1")

    quota = FakeQuotaRepository()
    gateway = FakeGateway(response=ProxyResponseEntity(success=False, status_code=503, error_message="upstream unavailable"))
    proxy, log = make_proxy(gateway=gateway, quota=quota)
    status, result = proxy.forward('{"model":"model"}', {}, auth_context=context)
    assert status == 503 and result["error"]["message"] == "upstream unavailable"
    assert quota.calls[-1] == ("release", "reservation-1")
    assert log.logs[0].error_message == "upstream unavailable"


@pytest.mark.parametrize(
    ("protocol", "endpoint", "expected_type"),
    [
        ("responses", "/v1/responses", "response"),
        ("completions", "/v1/completions", "text_completion"),
    ],
)
def test_forward_converts_compatibility_protocol_responses(protocol, endpoint, expected_type):
    proxy, _ = make_proxy()
    if protocol == "responses":
        body = '{"model":"model","input":"hi"}'
    else:
        body = '{"model":"model","prompt":"hi"}'

    status, result = proxy.forward(body, {}, endpoint=endpoint)

    assert status == 200 and result["object"] == expected_type


def test_forward_preserves_multipart_request_and_raw_audio_response():
    gateway = FakeGateway(response=ProxyResponseEntity(
        status_code=200, body="{}", raw_body=b"audio-bytes",
        content_type="audio/mpeg", response_headers={"X-Trace": "upstream"},
    ))
    proxy, _ = make_proxy(gateway=gateway)
    boundary = "unit-boundary"
    payload = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nmodel-a\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\n"
        "Content-Type: audio/wav\r\n\r\n\x00audio\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    status, result = proxy.forward(
        payload, {}, endpoint="/v1/audio/transcriptions",
        content_type=f"multipart/form-data; boundary={boundary}",
    )

    assert status == 200 and isinstance(result, RawProxyResponse)
    assert result.content == b"audio-bytes" and result.media_type == "audio/mpeg"
    assert result.headers == {"X-Trace": "upstream"}
    assert gateway.requests[0].raw_body == payload
    assert gateway.requests[0].body["model"] == "model-a"


def test_forward_response_scan_can_block_upstream_content():
    scanner = FakeSecurityScanner([
        SecurityScanResult(),
        SecurityScanResult(blocked=True, blocked_reason="unsafe output"),
    ])
    settings = SimpleNamespace(enabled=True, scan_response=True, fail_closed=True)
    proxy, log = make_proxy(scanner=scanner, settings=settings)

    status, result = proxy.forward('{"model":"model"}', {})

    assert status == 502 and result["error"]["code"] == "upstream_error"
    assert log.logs[0].error_message == "Response blocked by security policy"
    assert [call[1] for call in scanner.calls] == ["request", "response"]


@pytest.mark.asyncio
async def test_streaming_forward_records_chunks_usage_and_attempts():
    gateway = FakeGateway()
    log = FakeLogRepository()
    quota = FakeQuotaRepository()
    settings = SimpleNamespace(enabled=False, scan_response=False, fail_closed=True)
    proxy = ProxyService(gateway, None, settings, log, quota_repository=quota)
    context = AuthContext("api_key", "key-1", "client", allowed_models=frozenset({"model"}))

    frames = [frame async for frame in proxy.forward_stream_async(
        '{"model":"model","stream":true}', {}, auth_context=context,
        request_id="stream-1",
    )]

    assert frames[-1] == "data: [DONE]\n\n"
    assert any('"content":"ok"' in frame for frame in frames)
    assert log.attempts == [("stream-1", {"attempt": 1, "status": 200})]
    assert log.logs[0].response_choices and '"content"' in log.logs[0].response_choices
    assert log.logs[0].stream_status == "completed"
    assert log.logs[0].usage_source == "upstream"
    assert quota.calls[-1] == ("settle", "reservation-1", 5)


@pytest.mark.asyncio
async def test_streaming_forward_emits_safe_errors_and_releases_quota():
    gateway = FakeGateway()
    gateway.stream = lambda *_args, **_kwargs: _failed_stream()
    quota = FakeQuotaRepository()
    log = FakeLogRepository()
    proxy = ProxyService(
        gateway, None, SimpleNamespace(enabled=False, scan_response=False, fail_closed=True),
        log, quota_repository=quota,
    )
    context = AuthContext("api_key", "key-1", allowed_models=frozenset({"model"}))

    frames = [frame async for frame in proxy.forward_stream_async(
        '{"model":"model","stream":true}', {}, auth_context=context,
        request_id="stream-error",
    )]

    assert '"message": "upstream stream failed"' in frames[-1]
    assert quota.calls[-1] == ("release", "reservation-1")
    assert log.logs[0].stream_status == "error"


async def _failed_stream():
    yield ""
    raise RuntimeError("secret upstream error")


def test_build_log_truncates_large_responses_and_marks_security_findings():
    proxy, _ = make_proxy()
    scan = SecurityScanResult(
        risk_level="High", risk_score=80, summary="sensitive",
        findings=[SimpleNamespace(log_id=None)], sanitized=True,
    )

    entry = proxy._build_log(
        "log-1", "key-1", "model", "openai", False, 200, scan, "127.0.0.1",
        "request", "x" * 100_000, None, request_id="req-1", endpoint="/v1/test",
    )

    assert entry.sanitized is True and entry.security_action == "Sanitize"
    assert entry.risk_level == "High" and entry.risk_score == 80
    assert len(entry.response_choices) <= 65536 and entry.truncated is True
    assert entry.request_id == "req-1" and entry.endpoint == "/v1/test"
    assert entry._security_findings[0].log_id is None

