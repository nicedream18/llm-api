"""Default-deny authorization for scoped read-only knowledge base routes."""

from fastapi import Request

from app.application.errors import ApplicationError
from app.container import get_container


def require_kb_access(request: Request):
    context = getattr(request.state, "auth_context", None)
    if context is None:
        raise ApplicationError("Authentication required", 401, "authentication_error")
    if context.is_admin:
        return
    kb_id = request.path_params.get("kb_id")
    if kb_id:
        get_container().access_service.require(context, "kb", kb_id)
    elif request.method not in {"GET", "HEAD"}:
        raise ApplicationError(
            "Administrator authentication required", 403, "permission_denied"
        )
