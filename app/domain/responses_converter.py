"""Responses API ↔ OpenAI Chat Completions converter (aligned with Java ResponsesConverter.java)."""
import json
import time
import uuid
from typing import Any, Dict, List, Optional


class ResponsesConverter:
    """Bi-directional converter between Responses API and Chat Completions formats."""

    @staticmethod
    def responses_to_openai(body: str) -> str:
        """Convert Responses API request → OpenAI Chat Completions request.

        Conversion rules:
        1. input array → messages array
        2. item types: message → chat message; function_call → assistant with tool_calls;
           function_call_output → tool message; raw string → user message
        3. max_output_tokens → max_tokens
        4. instructions → system message prepend
        5. tools: flat format → nested Chat Completions format
        6. tool_choice, temperature, top_p pass through
        """
        req = json.loads(body)
        model = req.get("model", "")

        # Convert input → messages
        input_obj = req.get("input")
        messages = ResponsesConverter._convert_input_to_messages(input_obj)

        max_tokens = req.get("max_output_tokens", 4096)
        stream = req.get("stream", False)

        openai_body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if "temperature" in req:
            openai_body["temperature"] = req["temperature"]
        if "top_p" in req:
            openai_body["top_p"] = req["top_p"]

        # Convert tools
        ResponsesConverter._convert_tools(req, openai_body)

        # Pass through tool_choice
        if "tool_choice" in req:
            openai_body["tool_choice"] = req["tool_choice"]

        # Instructions → system message
        instructions = req.get("instructions")
        if instructions:
            openai_body["messages"].insert(0, {"role": "system", "content": instructions})

        return json.dumps(openai_body)

    @staticmethod
    def openai_to_responses(openai_response: str, model: str) -> str:
        """Convert OpenAI Chat Completions response → Responses API response.

        Conversion rules:
        1. choices[0].message.content → message output with output_text block
        2. choices[0].message.tool_calls → function_call output items
        3. finish_reason pass through
        4. usage: prompt_tokens→input_tokens, completion_tokens→output_tokens
        5. Generate id if not present
        """
        resp = json.loads(openai_response)
        choices = resp.get("choices", [])
        choice = choices[0] if choices else {}
        message = choice.get("message", {})

        content = message.get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"

        usage = resp.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        output: List[Dict[str, Any]] = []

        # Add function_call outputs for tool_calls
        tool_calls = message.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                arguments = func.get("arguments", "")
                call_id = tc.get("id", "")

                fc_item = {
                    "id": f"fc_{uuid.uuid4().hex}",
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": arguments,
                    "status": "completed",
                }
                output.append(fc_item)

        # Add text message output (always include if content non-empty or no other output)
        if content or not output:
            msg_item = {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
                "status": "completed",
            }
            output.append(msg_item)

        resp_id = resp.get("id") or f"resp_{uuid.uuid4()}"

        result = {
            "id": resp_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": model,
            "output": output,
            "usage": {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "status": "completed",
            "finish_reason": finish_reason,
        }
        return json.dumps(result)

    # ==================== Private Helpers ====================

    @staticmethod
    def _convert_input_to_messages(input_obj) -> List[Dict[str, Any]]:
        """Convert Responses API input to OpenAI messages array."""
        msgs: List[Dict[str, Any]] = []

        if isinstance(input_obj, list):
            for item in input_obj:
                if isinstance(item, str):
                    msgs.append({"role": "user", "content": item})
                    continue
                if not isinstance(item, dict):
                    continue

                item_type = item.get("type", "")

                if item_type == "function_call":
                    name = item.get("name", "")
                    arguments = item.get("arguments", "")
                    call_id = item.get("call_id", "")
                    msgs.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }],
                    })

                elif item_type == "function_call_output":
                    call_id = item.get("call_id", "")
                    output_val = item.get("output", "")
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": output_val,
                    })

                else:
                    # message or unknown type with role
                    if "role" in item:
                        role = item.get("role") or "user"
                        content_field = item.get("content")
                        if isinstance(content_field, list):
                            texts = []
                            for block in content_field:
                                if isinstance(block, dict):
                                    t = block.get("text")
                                    if t:
                                        texts.append(t)
                            content_val = "".join(texts)
                        elif isinstance(content_field, str):
                            content_val = content_field
                        else:
                            content_val = ""
                        msgs.append({"role": role, "content": content_val})
                    elif "text" in item:
                        msgs.append({"role": "user", "content": item.get("text", "")})
                    # else: skip unknown

        elif isinstance(input_obj, str):
            msgs.append({"role": "user", "content": input_obj})

        return msgs

    @staticmethod
    def _convert_tools(responses_body: dict, openai_body: dict):
        """Convert Responses API tools → Chat Completions tools format."""
        tools = responses_body.get("tools")
        if not tools:
            return

        openai_tools: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_type = tool.get("type", "")

            if tool_type == "function":
                # Already in Chat Completions format (has "function" field) — pass through
                if "function" in tool:
                    openai_tools.append(tool)
                    continue

                # Flat format → nested format
                func_obj: Dict[str, Any] = {
                    "name": tool.get("name"),
                    "parameters": tool.get("parameters"),
                }
                if "description" in tool:
                    func_obj["description"] = tool["description"]
                if "strict" in tool:
                    func_obj["strict"] = tool["strict"]

                openai_tools.append({"type": "function", "function": func_obj})
            # Skip non-function tools (web_search, file_search, etc.)

        if openai_tools:
            openai_body["tools"] = openai_tools
