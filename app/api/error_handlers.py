"""Shared handling of expected, client-safe application errors."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.errors import ApplicationError


async def application_error_handler(request: Request, exc: Exception):
    if not isinstance(exc, ApplicationError):
        return JSONResponse(status_code=500, content={"code": "0001", "info": "Internal server error", "data": None})
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "info": exc.message, "data": None},
        headers={"X-Request-ID": request_id} if request_id else None,
    )
