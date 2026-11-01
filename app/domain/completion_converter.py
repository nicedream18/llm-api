"""OpenAI legacy Completions and Chat Completions conversion."""

from __future__ import annotations

import json
from typing import Any


class CompletionConverter:
    @staticmethod
    def completions_to_chat(body: str) -> str:
        request = json.loads(body)
        prompt = request.get("prompt", "")
        prompts = prompt if isinstance(prompt, list) else [prompt]
        result: dict[str, Any] = {
            "model": request.get("model", ""),
            "messages": [{"role": "user", "content": str(item)} for item in prompts],
            "stream": bool(request.get("stream", False)),
        }
        for key in ("max_tokens", "temperature", "top_p", "stop", "seed", "logprobs", "n"):
            if key in request:
                result[key] = request[key]
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def chat_to_completions(body: str, model: str) -> str:
        response = json.loads(body)
        choices: list[dict[str, Any]] = []
        for choice in response.get("choices") or []:
            message = choice.get("message") or {}
            choices.append({
                "index": choice.get("index", len(choices)),
                "text": message.get("content") or "",
                "logprobs": choice.get("logprobs"),
                "finish_reason": choice.get("finish_reason"),
            })
        return json.dumps({
            "id": response.get("id"), "object": "text_completion",
            "created": response.get("created"), "model": response.get("model") or model,
            "choices": choices, "usage": response.get("usage") or {},
        }, ensure_ascii=False)
