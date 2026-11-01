import json

from app.domain.completion_converter import CompletionConverter
from app.domain.streaming import StreamCodec


def test_completion_prompt_string_and_array_convert_to_chat_messages():
    converted = json.loads(CompletionConverter.completions_to_chat(json.dumps({
        "model": "demo", "prompt": ["one", "two"], "max_tokens": 4, "stream": True,
    })))
    assert converted["messages"] == [{"role": "user", "content": "one"}, {"role": "user", "content": "two"}]
    assert converted["max_tokens"] == 4 and converted["stream"] is True


def test_chat_response_converts_to_text_completion():
    result = json.loads(CompletionConverter.chat_to_completions(json.dumps({
        "id": "chat-1", "model": "demo", "choices": [{"index": 0, "message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 3},
    }), "fallback"))
    assert result["object"] == "text_completion"
    assert result["choices"][0]["text"] == "hello"


def test_streaming_chat_chunks_convert_to_completion_text_chunks():
    codec = StreamCodec("openai", "completions", "demo")
    frames = codec.feed_line('data: {"id":"c1","model":"demo","choices":[{"delta":{"content":"hi"},"finish_reason":null}]}')
    frames += codec.feed_line("")
    payload = json.loads(next(line[6:] for line in frames[0].splitlines() if line.startswith("data: ")))
    assert payload["choices"][0]["text"] == "hi"
