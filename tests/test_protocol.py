from app.domain.protocol import ProtocolDetector


def test_protocol_detection_prefers_explicit_anthropic_headers():
    assert ProtocolDetector.detect({"anthropic-version": "2023-06-01"}, "{}") == "anthropic"
    assert ProtocolDetector.detect({"x-api-key": "client"}, "{}") == "anthropic"
    assert ProtocolDetector.detect(
        {"x-api-key": "client", "authorization": "Bearer client"}, "{}"
    ) == "openai"


def test_protocol_detection_uses_body_and_endpoint_signals():
    assert ProtocolDetector.detect({}, '{"input":"hello"}') == "responses"
    assert ProtocolDetector.detect({}, '{"input":"hello","messages":[]}') == "openai"
    assert ProtocolDetector.detect({}, "invalid json") == "openai"
    assert ProtocolDetector.detect({}, None) == "openai"
    assert ProtocolDetector.detect_endpoint({}, "{}", "/v1/completions/") == "completions"
    assert ProtocolDetector.detect_endpoint({}, '{"input":"hello"}', "/v1/responses") == "responses"


def test_api_key_extraction_prefers_nonempty_bearer_then_x_api_key():
    assert ProtocolDetector.extract_api_key({"authorization": "Bearer client-key"}) == "client-key"
    assert ProtocolDetector.extract_api_key({"authorization": "Bearer ", "x-api-key": " api-key "}) == "api-key"
    assert ProtocolDetector.extract_api_key({"authorization": "Basic token", "x-api-key": "fallback"}) == "fallback"
    assert ProtocolDetector.extract_api_key({"authorization": "Bearer "}) is None
    assert ProtocolDetector.extract_api_key({}) is None
    assert ProtocolDetector.extract_api_key(None) is None
