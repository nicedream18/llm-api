import json

import pytest

from app.domain.responses_converter import ResponsesConverter


def test_responses_request_converts_text_instructions_and_flat_function_tools():
    converted = json.loads(ResponsesConverter.responses_to_openai(json.dumps({
        "model": "gpt-test",
        "input": "summarize this",
        "instructions": "Be concise",
        "max_output_tokens": 90,
        "temperature": 0.2,
        "top_p": 0.8,
        "stream": True,
        "tool_choice": "auto",
        "tools": [
            {
                "type": "function", "name": "lookup", "description": "Lookup data",
                "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                "strict": True,
            },
            {"type": "web_search", "name": "ignored"},
        ],
    })))

    assert converted["messages"] == [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": "summarize this"},
    ]
    assert converted["model"] == "gpt-test"
    assert converted["max_tokens"] == 90 and converted["stream"] is True
    assert converted["temperature"] == 0.2 and converted["top_p"] == 0.8
    assert converted["tool_choice"] == "auto"
    assert converted["tools"] == [{
        "type": "function",
        "function": {
            "name": "lookup", "description": "Lookup data", "strict": True,
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
        },
    }]


def test_responses_request_converts_function_calls_and_multimodal_text_blocks():
    converted = json.loads(ResponsesConverter.responses_to_openai(json.dumps({
        "model": "gpt-test",
        "input": [
            {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "first"},
                {"type": "input_image", "image_url": "ignored"},
                {"type": "input_text", "text": " second"},
            ]},
            {"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": '{"id":"1"}'},
            {"type": "function_call_output", "call_id": "call-1", "output": "found"},
            {"text": "plain"},
            7,
            {"type": "unknown"},
        ],
    })))

    assert converted["messages"] == [
        {"role": "user", "content": "first second"},
        {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "call-1", "type": "function",
                "function": {"name": "lookup", "arguments": '{"id":"1"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "found"},
        {"role": "user", "content": "plain"},
    ]
    assert converted["max_tokens"] == 4096 and converted["stream"] is False


def test_responses_request_passes_through_nested_function_tool():
    tool = {"type": "function", "function": {"name": "lookup", "parameters": {}}}

    converted = json.loads(ResponsesConverter.responses_to_openai(json.dumps({
        "model": "gpt-test", "input": [{"role": "assistant", "content": "ok"}], "tools": [tool],
    })))

    assert converted["tools"] == [tool]


def test_chat_response_converts_text_tool_calls_finish_reason_and_usage(monkeypatch):
    monkeypatch.setattr("app.domain.responses_converter.time.time", lambda: 1234.5)
    converted = json.loads(ResponsesConverter.openai_to_responses(json.dumps({
        "id": "chat-1",
        "choices": [{
            "message": {
                "content": "ready",
                "tool_calls": [{
                    "id": "call-1", "function": {"name": "lookup", "arguments": '{"id":"1"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 3},
    }), "gpt-test"))

    assert converted["object"] == "response" and converted["id"] == "chat-1"
    assert converted["created_at"] == 1234 and converted["model"] == "gpt-test"
    assert converted["finish_reason"] == "tool_calls" and converted["status"] == "completed"
    assert converted["usage"] == {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7}
    assert converted["output"][0]["call_id"] == "call-1"
    assert converted["output"][0]["arguments"] == '{"id":"1"}'
    assert converted["output"][1]["content"] == [{"type": "output_text", "text": "ready"}]


def test_chat_response_supports_empty_choices_and_tool_only_response():
    empty = json.loads(ResponsesConverter.openai_to_responses(
        '{"choices":[]}', "fallback-model"
    ))
    tool_only = json.loads(ResponsesConverter.openai_to_responses(json.dumps({
        "choices": [{"message": {"tool_calls": [{
            "id": "call-1", "function": {"name": "lookup", "arguments": "{}"},
        }]}}],
    }), "gpt-test"))

    assert empty["model"] == "fallback-model"
    assert empty["output"][0]["content"] == [{"type": "output_text", "text": ""}]
    assert len(tool_only["output"]) == 1
    assert tool_only["output"][0]["type"] == "function_call"


def test_responses_converter_rejects_malformed_json():
    with pytest.raises(json.JSONDecodeError):
        ResponsesConverter.responses_to_openai("not-json")

