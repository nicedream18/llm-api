"""Per-operation model policy, shared by RAG, follow-ups and embeddings.

The context is invocation-local (including worker threads), never a mutable
attribute of a singleton service. All network calls in a scoped operation go
through the same application proxy that owns authorization, quota and usage.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from app.application.errors import ApplicationError
from app.domain.entities import ProxyResponseEntity
from app.types.auth import AuthContext


@dataclass
class ModelOperation:
    proxy: Any
    context: AuthContext | None
    remaining_calls: int = 32
    remaining_tokens: int = 65536
    deadline: float = 0

    def call(self, body: dict, endpoint: str) -> dict:
        size = max(1, len(json.dumps(body, ensure_ascii=False)) // 4)
        if (self.remaining_calls <= 0 or size >= self.remaining_tokens
                or time.monotonic() > self.deadline):
            raise ApplicationError("Knowledge operation budget exceeded", 429, "operation_budget_exceeded")
        self.remaining_calls -= 1
        body = dict(body)
        if endpoint.endswith("/chat/completions"):
            body["max_tokens"] = min(int(body.get("max_tokens") or 4096), self.remaining_tokens - size)
        status, result = self.proxy.forward(json.dumps(body), {}, auth_context=self.context, endpoint=endpoint)
        if status >= 400:
            error = result.get("error", {})
            raise ApplicationError(error.get("message", "Knowledge model request failed"), status,
                                   error.get("code", "model_request_failed"))
        usage = result.get("usage") or {}
        consumed = int(usage.get("total_tokens") or size)
        self.remaining_tokens -= max(size, consumed)
        return result


_operation: ContextVar[ModelOperation | None] = ContextVar("knowledge_model_operation", default=None)


@contextmanager
def model_operation(proxy, context: AuthContext | None):
    if proxy is None and context is not None and not context.is_admin:
        raise ApplicationError("Model policy service unavailable", 503, "model_policy_unavailable")
    value = ModelOperation(proxy, context, deadline=time.monotonic() + 120) if proxy is not None else None
    token = _operation.set(value)
    try:
        yield value
    finally:
        _operation.reset(token)


def scoped_model_call(body: dict, endpoint: str) -> dict | None:
    operation = _operation.get()
    return operation.call(body, endpoint) if operation is not None else None


def has_scoped_model_operation() -> bool:
    return _operation.get() is not None


def scoped_chat_response(body: dict) -> ProxyResponseEntity | None:
    result = scoped_model_call(body, "/v1/chat/completions")
    if result is None:
        return None
    usage = result.get("usage") or {}
    return ProxyResponseEntity(body=json.dumps(result), prompt_tokens=int(usage.get("prompt_tokens") or 0),
                               completion_tokens=int(usage.get("completion_tokens") or 0),
                               total_tokens=int(usage.get("total_tokens") or 0))
