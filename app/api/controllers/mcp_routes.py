"""Stateless MCP Streamable HTTP endpoint with JSON responses.

No session IDs or server-initiated SSE streams are issued. Each request is
authenticated by the outer middleware, including notifications and GETs.
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.config import config
from app.container import get_container

router = APIRouter()
logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "2025-06-18"
MAX_REQUEST_BYTES = 1024 * 1024


def _error(request_id, code, message, status=200):
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


@router.api_route("/mcp", methods=["GET", "DELETE"])
async def mcp_no_session(request: Request):
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_post(request: Request):
    # Also guard the endpoint when the router is mounted in a standalone app.
    origin = request.headers.get("origin")
    if origin is not None and origin not in config.cors_allowed_origins:
        return Response(status_code=403)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return Response(status_code=415)
    accept = {part.split(";", 1)[0].strip().lower() for part in request.headers.get("accept", "").split(",")}
    if not {"application/json", "text/event-stream"}.issubset(accept):
        return Response(status_code=406)
    version = request.headers.get("mcp-protocol-version")
    if version is not None and version != PROTOCOL_VERSION:
        return _error(None, -32600, "Unsupported protocol version", 400)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            return Response(status_code=413)
    try:
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _error(None, -32700, "Parse error", 400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid Request", 400)
    rpc_id = message.get("id")
    if "id" in message and (isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, int))):
        return _error(None, -32600, "Invalid Request", 400)
    method = message.get("method")
    if not isinstance(method, str) or "result" in message or "error" in message:
        return _error(rpc_id, -32600, "Invalid Request", 400)
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(rpc_id, -32602, "Invalid params", 400) if "id" in message else Response(status_code=400)
    # Notifications never execute tools or produce JSON-RPC responses.
    if "id" not in message:
        return Response(status_code=202)
    if method == "initialize":
        client_info = params.get("clientInfo")
        if (not isinstance(params.get("protocolVersion"), str)
                or not isinstance(params.get("capabilities"), dict)
                or not isinstance(client_info, dict)
                or not all(isinstance(client_info.get(key), str) for key in ("name", "version"))):
            return _error(rpc_id, -32602, "Invalid initialize params")
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "WaLiAPI MCP Server", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        if params.get("cursor") is not None:
            return _error(rpc_id, -32602, "Invalid cursor")
        result = await asyncio.to_thread(get_container().mcp_service.list_tools,
                                         getattr(request.state, "auth_context", None))
    elif method == "tools/call":
        service = get_container().mcp_service
        try:
            arguments = service.validate_arguments(params.get("name"), params.get("arguments", {}))
        except ValueError as exc:
            return _error(rpc_id, -32602, str(exc))
        logger.info("MCP tool requested: request_id=%s tool=%s principal_id=%s",
                    getattr(request.state, "request_id", None), params["name"],
                    getattr(getattr(request.state, "auth_context", None), "principal_id", None), extra={
            "request_id": getattr(request.state, "request_id", None),
            "tool": params["name"],
            "principal_id": getattr(getattr(request.state, "auth_context", None), "principal_id", None),
        })
        result = await asyncio.to_thread(service.call_tool, params["name"], arguments,
                                         getattr(request.state, "auth_context", None),
                                         getattr(request.state, "request_id", None))
    else:
        return _error(rpc_id, -32601, "Method not found")
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})
