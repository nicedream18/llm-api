import json

import pytest

from app.domain.agent_service import DEFAULT_CHAT_MODEL, AgentChatService
from app.domain.entities import AgentConfigEntity, ProxyResponseEntity


class FakeAgentRepository:
    def __init__(self, config_json=None):
        self.config = AgentConfigEntity(agent_id="agent-1", config_json=config_json)

    def get_agent_by_agent_id(self, _agent_id):
        return self.config


class FakeChannelRepository:
    def __init__(self, keys=None, error=None):
        self.keys = keys or []
        self.error = error

    def get_all_api_keys(self):
        if self.error:
            raise self.error
        return self.keys


class FakeGateway:
    def __init__(self, response=None, chunks=None, stream_error=None):
        self.response = response or ProxyResponseEntity(
            body=json.dumps({"choices": [{"message": {"content": "reply"}}]})
        )
        self.chunks = chunks or []
        self.stream_error = stream_error
        self.requests = []

    def forward_sync(self, request):
        self.requests.append(request)
        return self.response

    async def stream(self, request):
        self.requests.append(request)
        for chunk in self.chunks:
            yield chunk
        if self.stream_error:
            raise self.stream_error


def make_service(config_json=None, response=None, chunks=None, stream_error=None):
    repository = FakeAgentRepository(config_json)
    gateway = FakeGateway(response, chunks, stream_error)
    service = AgentChatService(repository, FakeChannelRepository(), gateway)
    return service, gateway


def test_create_session_seeds_system_instruction():
    service, _ = make_service('{"instruction":"Use concise answers"}')

    session_id = service.create_session("agent-1", "user-1")

    assert service._sessions[session_id] == [
        {"role": "system", "content": "Use concise answers"}
    ]


@pytest.mark.parametrize("config_json", ["{broken", "[]"])
def test_malformed_or_non_object_agent_config_is_ignored(config_json):
    service, _ = make_service(config_json)

    session_id = service.create_session("agent-1", "user-1")
    answer = service.handle_message("agent-1", session_id, "user-1", "question")

    assert answer == "reply"
    assert service._sessions[session_id] == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "reply"},
    ]


def test_handle_message_uses_configured_model_and_seeds_unknown_session():
    service, gateway = make_service(
        '{"instruction":"Follow policy","model":"custom-model"}'
    )

    answer = service.handle_message("agent-1", "session-unknown", "user-1", "question")

    assert answer == "reply"
    request = gateway.requests[0]
    assert request.model == "custom-model"
    assert request.body["stream"] is False
    assert request.body["messages"] == [
        {"role": "system", "content": "Follow policy"},
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "reply"},
    ]


def test_handle_message_uses_default_model_and_reports_gateway_failure():
    service, gateway = make_service(
        response=ProxyResponseEntity(success=False, error_message="upstream unavailable")
    )
    session_id = service.create_session("agent-1", "user-1")

    answer = service.handle_message("agent-1", session_id, "user-1", "question")

    assert answer == "对话失败: upstream unavailable"
    assert gateway.requests[0].model == DEFAULT_CHAT_MODEL
    assert service._sessions[session_id] == [{"role": "user", "content": "question"}]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (ProxyResponseEntity(body=""), "网关返回空响应"),
        (ProxyResponseEntity(body="not-json"), "对话失败:"),
    ],
)
def test_handle_message_reports_empty_or_invalid_gateway_payload(response, expected):
    service, _ = make_service(response=response)

    answer = service.handle_message("agent-1", "session-1", "user-1", "question")

    assert answer.startswith(expected)


def test_stream_message_emits_deltas_and_persists_completed_assistant_turn():
    chunks = [
        'data: {"choices":[{"delta":{"content":"hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
        "not-json",
    ]
    service, gateway = make_service('{"instruction":"Be helpful","model":"stream-model"}', chunks=chunks)
    session_id = service.create_session("agent-1", "user-1")
    received = []
    errors = []
    completions = []

    service.handle_message_stream(
        "agent-1", session_id, "user-1", "question", received.append,
        errors.append, lambda: completions.append("complete"),
    )

    assert received == ["hel", "lo"]
    assert errors == [] and completions == ["complete"]
    assert gateway.requests[0].model == "stream-model"
    assert gateway.requests[0].body["stream"] is True
    assert service._sessions[session_id][-1] == {"role": "assistant", "content": "hello"}


def test_stream_failure_is_reported_without_completing_turn():
    failure = RuntimeError("stream disconnected")
    service, _ = make_service(stream_error=failure)
    session_id = service.create_session("agent-1", "user-1")
    errors = []
    completions = []

    service.handle_message_stream(
        "agent-1", session_id, "user-1", "question", lambda _chunk: None,
        errors.append, lambda: completions.append("complete"),
    )

    assert errors == [failure]
    assert completions == []
    assert service._sessions[session_id] == [{"role": "user", "content": "question"}]
