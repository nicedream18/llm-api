import json

from app.domain.anthropic_converter import AnthropicConverter


def test_anthropic_messages_convert_to_chat_with_system_tools_and_tool_result():
    body = {
        "model": "claude-test",
        "system": [{"type": "text", "text": "Be concise"}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": "x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": [{"type": "text", "text": "ok"}]}]},
        ],
        "tools": [{"name": "lookup", "description": "Find a value", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}],
        "tool_choice": {"type": "tool", "name": "lookup"},
        "max_tokens": 100,
    }
    converted = json.loads(AnthropicConverter.messages_to_openai(json.dumps(body)))
    assert converted["messages"][0] == {"role": "system", "content": "Be concise"}
    assert converted["messages"][1] == {"role": "user", "content": "hi"}
    assert converted["messages"][2]["tool_calls"][0]["function"]["name"] == "lookup"
    assert converted["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "ok"}
    assert converted["tools"][0]["function"]["parameters"]["properties"]["q"]["type"] == "string"
    assert converted["tool_choice"]["function"]["name"] == "lookup"


def test_chat_response_converts_text_tool_call_and_usage_to_messages():
    response = {
        "id": "chat_1",
        "model": "gpt-test",
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I will check",
                "tool_calls": [{"id": "call_1", "function": {"name": "lookup", "arguments": '{"q":"x"}'}}],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 3},
    }
    converted = json.loads(AnthropicConverter.chat_to_messages(json.dumps(response), "fallback"))
    assert converted["id"] == "chat_1"
    assert converted["stop_reason"] == "tool_use"
    assert converted["content"][0] == {"type": "text", "text": "I will check"}
    assert converted["content"][1]["type"] == "tool_use"
    assert converted["content"][1]["input"] == {"q": "x"}
    assert converted["usage"] == {"input_tokens": 4, "output_tokens": 3}
