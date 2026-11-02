"""Authentication middleware for admin, MCP and data-plane requests."""
from __future__ import annotations

import asyncio
import hmac
import logging
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Match

from app.application.services.auth_service import (
    AdminAuthService,
    ApiKeyAuthorizer,
    AuthError,
)
from app.config import config
from app.container import get_container
from app.types.auth import AuthContext

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/api/v1/health", "/api/v1/auth/login", "/docs", "/openapi.json", "/redoc"}
GATEWAY_PREFIXES = ("/v1/chat/completions", "/v1/completions", "/v1/responses", "/v1/embeddings", "/v1/images/", "/v1/audio/", "/v1/messages")
ADMIN_PREFIXES = ("/api/v1/channels", "/api/v1/api-keys", "/api/v1/logs", "/api/v1/security", "/api/v1/agents", "/api/v1/software", "/api/v1/providers", "/api/v1/platform")
KB_PREFIX = "/api/v1/kb"
MCP_PREFIX = "/api/mcp"
WIKI_PREFIX = "/api/v1/wiki"


def _error(exc: AuthError, request_id: str, admin: bool = False) -> JSONResponse:
    content = {"code": "0008" if exc.status_code == 401 else "0009", "info": "未授权访问" if exc.status_code == 401 else "权限不足", "data": None} if admin else {"error": {"message": exc.message, "type": exc.code, "code": exc.code}}
    response = JSONResponse(status_code=exc.status_code, content=content)
    response.headers["X-Request-ID"] = request_id
    return response


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _kb_api_key_read_allowed(method: str, path: str, prefix: str) -> bool:
    """Allow safe reads and read-only search/answer POSTs for data-plane keys."""
    if method in {"GET", "HEAD"}:
        return True
    suffix = path[len(prefix):].strip("/")
    parts = suffix.split("/") if suffix else []
    return bool(parts and len(parts) == 2 and parts[1] in {"ask", "search", "deep-research"} and method == "POST")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = getattr(request.state, "request_id", None)
        candidate = request.headers.get("x-request-id", "").strip()
        request_id = request_id or (candidate[:128] if candidate and all(c.isalnum() or c in "-_." for c in candidate) else uuid.uuid4().hex)
        request.state.request_id = request_id
        context = getattr(request.state, "auth_context", None)
        audit = bool(context and context.is_admin and request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/v1/"))
        if audit:
            repository = get_container().admin_repo
            routes = getattr(request.app, "routes", [])
            template = next((getattr(route, "path", "unmatched") for route in routes if route.matches(request.scope)[0] == Match.FULL), "unmatched")
            action = f"{request.method}:{template}"[:118]
            ip = request.client.host if request.client else None
            await asyncio.to_thread(repository.write_audit, context.principal_name, "start:" + action, request_id, ip, True)
        try:
            response = await call_next(request)
        except Exception:
            if audit:
                await asyncio.to_thread(repository.write_audit, context.principal_name, "end:" + action, request_id, ip, False)
            raise
        if audit:
            await asyncio.to_thread(repository.write_audit, context.principal_name, "end:" + action, request_id, ip, response.status_code < 400)
        response.headers["X-Request-ID"] = request_id
        return response


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        candidate = request.headers.get("x-request-id", "").strip()
        request_id = candidate[:128] if candidate and all(c.isalnum() or c in "-_." for c in candidate) else uuid.uuid4().hex
        request.state.request_id = request_id
        if path in PUBLIC_PATHS or _under(path, "/static"):
            return await call_next(request)

        container = get_container()
        admin = container.admin_service.auth if hasattr(container, "admin_service") else AdminAuthService()
        api_authorizer = ApiKeyAuthorizer(container.channel_repo)
        bearer = request.headers.get("authorization", "")
        bearer_token = bearer[7:].strip() if bearer.lower().startswith("bearer ") else None
        cookie_token = request.cookies.get("waliapi_admin_session")

        admin_context = admin.verify_admin_token(bearer_token) or (await asyncio.to_thread(admin.verify_session, cookie_token) if cookie_token else None)
        if admin_context and cookie_token and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in config.cors_allowed_origins:
                return _error(AuthError("Origin is not allowed", 403, "permission_error"), request_id, admin=True)
        if _under(path, "/api/v1/auth"):
            if not admin_context:
                return _error(AuthError("Admin authentication required", 401, "authentication_error"), request_id, admin=True)
            request.state.auth_context = admin_context
            return await call_next(request)

        if any(_under(path, p) for p in ADMIN_PREFIXES):
            if not admin_context:
                return _error(AuthError("Admin authentication required", 401, "authentication_error"), request_id, admin=True)
            request.state.auth_context = admin_context
            return await call_next(request)

        if _under(path, MCP_PREFIX) or _under(path, "/mcp"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.cors_allowed_origins:
                return _error(AuthError("Origin is not allowed", 403, "permission_error"), request_id)
            mcp_token = bearer_token or request.headers.get("x-mcp-token")
            if config.auth.mcp_token and mcp_token and hmac.compare_digest(mcp_token.encode(), config.auth.mcp_token.encode()):
                request.state.auth_context = admin_context or AuthContext("mcp", "mcp-token", "mcp")
                return await call_next(request)
            if config.auth.mcp_api_key_access:
                try:
                    request.state.auth_context = await run_in_threadpool(api_authorizer.authenticate, mcp_token)
                    return await call_next(request)
                except AuthError as exc:
                    return _error(exc, request_id)
            return _error(AuthError("MCP token required", 401, "authentication_error"), request_id)

        if _under(path, WIKI_PREFIX):
            if admin_context:
                request.state.auth_context = admin_context
                return await call_next(request)
            read_only = request.method in {"GET", "HEAD"} or (
                request.method == "POST" and path.endswith("/ask")
            )
            if not read_only:
                return _error(AuthError("Wiki writes require administrator authentication", 403, "permission_error"), request_id)
            try:
                request.state.auth_context = await run_in_threadpool(api_authorizer.authenticate, bearer_token or request.headers.get("x-api-key"))
                return await call_next(request)
            except AuthError as exc:
                return _error(exc, request_id)

        if _under(path, KB_PREFIX):
            if admin_context:
                request.state.auth_context = admin_context
                return await call_next(request)
            if not _kb_api_key_read_allowed(request.method, path, KB_PREFIX):
                return _error(AuthError("Read-only API key cannot modify knowledge bases", 403, "permission_error"), request_id)
            try:
                request.state.auth_context = await run_in_threadpool(api_authorizer.authenticate, bearer_token or request.headers.get("x-api-key"))
                return await call_next(request)
            except AuthError as exc:
                return _error(exc, request_id)

        if _under(path, "/api/v1"):
            if not admin_context:
                return _error(AuthError("Admin authentication required", 401, "authentication_error"), request_id, admin=True)
            request.state.auth_context = admin_context
            return await call_next(request)

        if path == "/v1/models" and not config.auth.models_require_api_key:
            return await call_next(request)
        if any(path == p or path.startswith(p) for p in GATEWAY_PREFIXES) or path == "/v1/models":
            try:
                request.state.auth_context = await run_in_threadpool(api_authorizer.authenticate, bearer_token or request.headers.get("x-api-key"))
                return await call_next(request)
            except AuthError as exc:
                return _error(exc, request_id)

        return await call_next(request)
