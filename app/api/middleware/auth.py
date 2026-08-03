"""API key authentication middleware."""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PROTECTED_PREFIXES = (
    "/v1/chat/completions", "/v1/completions", "/v1/responses", "/v1/embeddings",
    "/v1/images/generations", "/v1/audio/transcriptions", "/v1/audio/speech", "/v1/messages",
)

WHITELIST_PREFIXES = (
    "/health", "/api/v1/", "/api/mcp", "/v1/models",
)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        for wl in WHITELIST_PREFIXES:
            if path.startswith(wl):
                return await call_next(request)

        needs_auth = any(path.startswith(p) for p in PROTECTED_PREFIXES)
        if not needs_auth:
            return await call_next(request)

        api_key = self._extract_api_key(request)
        if not api_key:
            logger.warning(f"Missing API key for path: {path}")
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "Missing API key", "type": "authentication_error"}},
            )

        request.state.api_key = api_key
        return await call_next(request)

    def _extract_api_key(self, request):
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            key = auth[7:].strip()
            if key:
                return key
        x_api_key = request.headers.get("x-api-key")
        if x_api_key and x_api_key.strip():
            return x_api_key.strip()
        return None
