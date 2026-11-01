"""Conversions between Anthropic Messages and OpenAI Chat Completions."""

from __future__ import annotations

import json
import uuid
from typing import Any


class AnthropicConverter:
    """Translate the common Anthropic Messages contract to/from OpenAI chat."""

    @staticmethod
    def messages_to_openai(body: str) -> str:
        request = json.loads(body)
        messages: list[dict[str, Any]] = []
        system = request.get("system")
        if system:
            if isinstance(system, list):
                system = "\n".join(
                    str(block.get("text", ""))
                    for block in system
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            messages.append({"role": "system", "content": system})

        for message in request.get("messages") or []:
            if not isinstance(message, dict):
                continue
            role = message.get("role", "user")
            content = message.get("content", "")
            if isinstance(content, list):
                text_parts: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                tool_outputs: list[dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif block_type == "tool_use":
                        tool_calls.append({
                            "id": block.get("id") or f"call_{uuid.uuid4().hex}",
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                            },
                        })
                    elif block_type == "tool_result":
                        output = block.get("content", "")
                        if isinstance(output, list):
                            output = "".join(
                                str(part.get("text", "")) for part in output
                                if isinstance(part, dict) and part.get("type") == "text"
                            )
                        tool_outputs.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
                        })
                if tool_calls:
                    messages.append({"role": "assistant", "content": "".join(text_parts) or None, "tool_calls": tool_calls})
                elif text_parts:
                    messages.append({"role": role, "content": "".join(text_parts)})
                messages.extend(tool_outputs)
            elif isinstance(content, str):
                messages.append({"role": role, "content": content})

        result: dict[str, Any] = {
            "model": request.get("model", ""),
            "messages": messages,
            "max_tokens": int(request.get("max_tokens", 4096)),
            "stream": bool(request.get("stream", False)),
        }
        for key in ("temperature", "top_p"):
            if key in request:
                result[key] = request[key]
        if request.get("stop_sequences"):
            result["stop"] = request["stop_sequences"]
        AnthropicConverter._convert_tools(request.get("tools"), result)
        AnthropicConverter._convert_tool_choice(request.get("tool_choice"), result)
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def chat_to_messages(body: str, model: str) -> str:
        response = json.loads(body)
        choices = response.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        content: list[dict[str, Any]] = []
        text = message.get("content")
        if isinstance(text, str) and text:
            content.append({"type": "text", "text": text})
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (ValueError, TypeError):
                    arguments = {}
            content.append({
                "type": "tool_use",
                "id": call.get("id") or f"toolu_{uuid.uuid4().hex}",
                "name": function.get("name", ""),
                "input": arguments if isinstance(arguments, dict) else {},
            })
        usage = response.get("usage") or {}
        finish = choice.get("finish_reason") or "stop"
        stop_reason = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}.get(finish, finish)
        result = {
            "id": response.get("id") or f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": response.get("model") or model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                "output_tokens": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
            },
        }
        return json.dumps(result, ensure_ascii=False)

    @staticmethod
    def _convert_tools(tools: Any, target: dict[str, Any]) -> None:
        if not isinstance(tools, list):
            return
        converted = []
        for tool in tools:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            function: dict[str, Any] = {
                "name": tool["name"],
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
            if "description" in tool:
                function["description"] = tool["description"]
            converted.append({"type": "function", "function": function})
        if converted:
            target["tools"] = converted

    @staticmethod
    def _convert_tool_choice(choice: Any, target: dict[str, Any]) -> None:
        if not isinstance(choice, dict):
            return
        choice_type = choice.get("type")
        if choice_type == "auto":
            target["tool_choice"] = "auto"
        elif choice_type == "any":
            target["tool_choice"] = "required"
        elif choice_type == "tool" and choice.get("name"):
            target["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
