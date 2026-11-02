"""MCP Streamable HTTP endpoint with optional authenticated sessions.

JSON responses are used for client requests. Sessions provide lifecycle and
identity continuity; an optional SSE stream carries server notifications.
"""
import asyncio
import json
import logging
import secrets
import time
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.config import config
from app.container import get_container

router = APIRouter()
logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "2025-06-18"
MAX_REQUEST_BYTES = 1024 * 1024
SESSION_TTL_SECONDS = 3600
_sessions: dict[str, tuple[float, tuple[str | None, str | None]]] = {}
_session_events: dict[str, asyncio.Queue[str]] = {}
RequestKey = tuple[str | None, str | None, str | None, str | int]
_running_requests: dict[RequestKey, asyncio.Task] = {}
_request_cancellations: dict[RequestKey, asyncio.Event] = {}
MAX_ACTIVE_REQUESTS = 128


def _request_key(request: Request, rpc_id: str | int) -> RequestKey:
    return (*_principal(request), request.headers.get("mcp-session-id"), rpc_id)


def _session_repository():
    try:
        return getattr(get_container(), "mcp_session_repo", None)
    except (AttributeError, RuntimeError):
        return None


def _principal(request: Request) -> tuple[str | None, str | None]:
    context = getattr(request.state, "auth_context", None)
    return getattr(context, "principal_type", None), getattr(context, "principal_id", None)


def _cleanup_sessions(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    for session_id, (expires, _owner) in list(_sessions.items()):
        if expires <= current:
            _sessions.pop(session_id, None)
            _session_events.pop(session_id, None)
    repository = _session_repository()
    if repository is not None:
        try:
            repository.cleanup_expired()
        except Exception:
            logger.warning("Failed to clean up persistent MCP sessions", exc_info=True)


def _validate_session(request: Request) -> bool:
    session_id = request.headers.get("mcp-session-id")
    if not session_id:
        return True
    repository = _session_repository()
    if repository is not None:
        try:
            return repository.validate(session_id, _principal(request), SESSION_TTL_SECONDS)
        except Exception:
            logger.warning("Failed to validate persistent MCP session", exc_info=True)
            return False
    _cleanup_sessions()
    record = _sessions.get(session_id)
    if record is None or record[1] != _principal(request):
        return False
    _sessions[session_id] = (time.monotonic() + SESSION_TTL_SECONDS, record[1])
    return True


def _replay_error(status: str):
    """Map persistent replay state to an explicit HTTP/protocol error."""
    if status in {"not_found", "expired", "owner_mismatch"}:
        return Response(status_code=404, headers={"Mcp-Error": status})
    if status == "gap":
        return Response(status_code=409, headers={"Mcp-Error": "event_gap"})
    return None


def _persistent_replay(session_id: str, request: Request, after_event_id: int):
    repository = _session_repository()
    if repository is None:
        return None
    try:
        checked = repository.replay_checked(session_id, _principal(request), after_event_id)
    except AttributeError:
        # Compatibility for deployments that provide the old repository object.
        return repository.replay(session_id, _principal(request), after_event_id)
    error = _replay_error(checked.status)
    if error is not None:
        return error
    return checked.events


def _new_session(request: Request) -> str:
    _cleanup_sessions()
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = (time.monotonic() + SESSION_TTL_SECONDS, _principal(request))
    _session_events[session_id] = asyncio.Queue(maxsize=64)
    repository = _session_repository()
    if repository is not None:
        try:
            repository.create(session_id, _principal(request), SESSION_TTL_SECONDS)
        except Exception:
            logger.warning("Failed to persist MCP session", exc_info=True)
            _sessions.pop(session_id, None)
            _session_events.pop(session_id, None)
            raise
    return session_id


def publish_session_event(session_id: str, method: str, params: dict | None = None) -> bool:
    """Queue a server notification for a connected Streamable HTTP client.

    The queue is bounded so a disconnected client cannot grow process memory.
    Events are best effort; the request path never waits for an SSE consumer.
    """
    queue = _session_events.get(session_id)
    event_id = None
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    repository = _session_repository()
    if repository is not None:
        try:
            event_id = repository.append_event(session_id, payload)
            if event_id is None:
                return False
        except Exception:
            logger.warning("Failed to persist MCP session event", exc_info=True)
            return False
    if queue is None:
        return event_id is not None
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    frame = f"id: {event_id}\nevent: message\ndata: {encoded}\n\n" if event_id is not None else f"event: message\ndata: {encoded}\n\n"
    try:
        queue.put_nowait(frame)
    except asyncio.QueueFull:
        return False
    return True


def _error(request_id, code, message, status=200):
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


@router.api_route("/mcp", methods=["GET", "DELETE"])
async def mcp_no_session(request: Request):
    if request.method == "GET":
        session_id = request.headers.get("mcp-session-id")
        if not session_id or not _validate_session(request):
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})
        accept = {part.split(";", 1)[0].strip().lower() for part in request.headers.get("accept", "").split(",")}
        if "text/event-stream" not in accept:
            return Response(status_code=406)
        queue = _session_events.setdefault(session_id, asyncio.Queue(maxsize=64))
        try:
            last_event_id = max(0, int(request.headers.get("last-event-id", "0") or 0))
        except ValueError:
            last_event_id = 0
        repository = _session_repository()
        initial_replay = _persistent_replay(session_id, request, last_event_id)
        if isinstance(initial_replay, Response):
            return initial_replay

        async def event_stream():
            yield f"event: ready\ndata: {json.dumps({'sessionId': session_id}, separators=(',', ':'))}\n\n"
            cursor = last_event_id
            if isinstance(initial_replay, list):
                for item in initial_replay:
                    cursor = max(cursor, int(item["event_id"]))
                    payload = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {item['event_id']}\nevent: message\ndata: {payload}\n\n"
            while not await request.is_disconnected():
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=1)
                    event_id = 0
                    if frame.startswith("id:"):
                        try:
                            event_id = int(frame.splitlines()[0][3:].strip())
                        except ValueError:
                            event_id = 0
                    if event_id and event_id <= cursor:
                        continue
                    if event_id:
                        cursor = event_id
                    yield frame
                except TimeoutError:
                    # The queue is process-local. Polling the repository keeps a
                    # session usable after a worker restart or on another worker.
                    if repository is not None:
                        try:
                            replayed = _persistent_replay(session_id, request, cursor)
                            if isinstance(replayed, Response):
                                return
                            for item in replayed or []:
                                cursor = max(cursor, int(item["event_id"]))
                                payload = json.dumps(item["payload"], ensure_ascii=False, separators=(",", ":"))
                                yield f"id: {item['event_id']}\nevent: message\ndata: {payload}\n\n"
                            continue
                        except Exception:
                            logger.warning("Failed to replay MCP session events", exc_info=True)
                    yield ": keepalive\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
    if request.method == "DELETE":
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return Response(status_code=405, headers={"Allow": "POST, DELETE"})
        _cleanup_sessions()
        repository = _session_repository()
        if repository is not None:
            checked = _persistent_replay(session_id, request, 0)
            if isinstance(checked, Response):
                return checked
        elif session_id not in _sessions:
            return Response(status_code=404)
        if not _validate_session(request):
            return Response(status_code=403)
        _sessions.pop(session_id, None)
        _session_events.pop(session_id, None)
        if repository is not None:
            repository.delete(session_id)
        return Response(status_code=204)
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
    if not _validate_session(request):
        return Response(status_code=404)
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
    if "id" in message:
        rpc_id = cast(str | int, rpc_id)
    method = message.get("method")
    if not isinstance(method, str) or "result" in message or "error" in message:
        return _error(rpc_id, -32600, "Invalid Request", 400)
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(rpc_id, -32602, "Invalid params", 400) if "id" in message else Response(status_code=400)
    # Notifications never execute tools or produce JSON-RPC responses.
    if "id" not in message:
        if method == "notifications/cancelled":
            cancelled_id = params.get("requestId")
            if isinstance(cancelled_id, (str, int)) and not isinstance(cancelled_id, bool):
                signal = _request_cancellations.get(_request_key(request, cancelled_id))
                if signal is not None:
                    signal.set()
            # Cancellation applies only to an active call. Do not accumulate
            # unbounded tombstones that could cancel a future reuse of an ID.
        return Response(status_code=202)
    if method == "initialize":
        if request.headers.get("mcp-session-id"):
            return _error(rpc_id, -32600, "Initialize must not include a session ID", 400)
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
            service.validate_arguments(params.get("name"), params.get("arguments", {}))
            arguments = params.get("arguments", {})
        except ValueError as exc:
            return _error(rpc_id, -32602, str(exc))
        logger.info("MCP tool requested: request_id=%s tool=%s principal_id=%s",
                    getattr(request.state, "request_id", None), params["name"],
                    getattr(getattr(request.state, "auth_context", None), "principal_id", None), extra={
            "request_id": getattr(request.state, "request_id", None),
            "tool": params["name"],
            "principal_id": getattr(getattr(request.state, "auth_context", None), "principal_id", None),
        })
        request_key = _request_key(request, cast(str | int, rpc_id))
        if request_key in _running_requests:
            return _error(rpc_id, -32600, "Request ID is already active")
        if len(_running_requests) >= MAX_ACTIVE_REQUESTS:
            return _error(rpc_id, -32000, "Tool execution capacity exceeded", 503)
        signal = asyncio.Event()
        task = asyncio.create_task(run_in_threadpool(service.call_tool, params["name"], arguments,
                                                     getattr(request.state, "auth_context", None),
                                                     getattr(request.state, "request_id", None)))
        _running_requests[request_key] = task
        _request_cancellations[request_key] = signal
        def completed(done):
            if _running_requests.get(request_key) is done:
                _running_requests.pop(request_key, None)
                _request_cancellations.pop(request_key, None)
            if not done.cancelled() and done.exception() is not None:
                logger.error("MCP background execution failed after request completion")
        task.add_done_callback(completed)
        cancellation = asyncio.create_task(signal.wait())
        try:
            await asyncio.wait({task, cancellation}, return_when=asyncio.FIRST_COMPLETED)
            if signal.is_set() and not task.done():
                return _error(rpc_id, -32800, "Request cancelled; execution may still be running")
            result = await asyncio.shield(task)
        finally:
            # Keep the execution registered if the HTTP waiter disconnects.
            # Its synchronous connector still finishes and audits its outcome.
            cancellation.cancel()
    else:
        return _error(rpc_id, -32601, "Method not found")
    response = JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})
    if method == "initialize":
        response.headers["Mcp-Session-Id"] = _new_session(request)
    return response
