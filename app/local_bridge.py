"""Newline JSON-RPC stdio bridge to the authenticated Streamable HTTP MCP endpoint."""

import json
import os

import httpx

from app.domain.streaming import SSEDecoder
from app.local_config import gateway_url


def bridge(input_stream, output_stream, url, allow_remote=False, client=None):
    endpoint = gateway_url(url, allow_remote) + "/mcp"
    token = os.environ.get("WALIAPI_MCP_TOKEN", "")
    if not token: raise ValueError("WALIAPI_MCP_TOKEN is required")
    session = None
    owned = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=False)
    try:
        while True:
            line = input_stream.readline(1_048_577)
            if not line: break
            if len(line) > 1_048_576: raise ValueError("MCP message exceeds size limit")
            request = json.loads(line)
            if not isinstance(request, dict): raise TypeError("MCP message must be an object")
            headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
            if session: headers["Mcp-Session-Id"] = session
            try:
                with client.stream("POST", endpoint, json=request, headers=headers) as response:
                    if response.is_error or response.is_redirect:
                        raise ValueError("MCP upstream rejected request")
                    session = response.headers.get("mcp-session-id", session)
                    chunks = []; length = 0
                    for chunk in response.iter_bytes():
                        length += len(chunk)
                        if length > 2_000_000: raise ValueError("MCP response exceeds limit")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    content_type = response.headers.get("content-type", "")
                result = None
                if content:
                    if "text/event-stream" in content_type:
                        parser = SSEDecoder()
                        messages = [event for line in (content.decode() + "\n\n").splitlines() if (event := parser.feed_line(line)) is not None]
                        result = next((json.loads(event.data) for event in messages if event.data and event.data != "[DONE]" and json.loads(event.data).get("id") == request.get("id")), None)
                    else: result = json.loads(content)
                if "id" in request and result is not None:
                    encoded = json.dumps(result, ensure_ascii=False).replace(json.dumps(token, ensure_ascii=False)[1:-1], "[REDACTED]")
                    output_stream.write(encoded + "\n"); output_stream.flush()
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                if "id" in request:
                    output_stream.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32603, "message": "MCP bridge upstream failure"}}) + "\n"); output_stream.flush()
    finally:
        if owned: client.close()
