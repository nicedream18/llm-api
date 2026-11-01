"""Unified API response wrapper."""
from typing import Any

from pydantic import BaseModel

from app.types.enums import ResponseCode


class Response(BaseModel):
    code: str = ResponseCode.SUCCESS.code
    info: str = ResponseCode.SUCCESS.info
    data: Any | None = None

    @staticmethod
    def success(data: Any = None) -> "Response":
        return Response(code=ResponseCode.SUCCESS.code, info=ResponseCode.SUCCESS.info, data=data)

    @staticmethod
    def fail(code: ResponseCode = ResponseCode.UN_ERROR, info: str | None = None) -> "Response":
        return Response(code=code.code, info=info or code.info, data=None)


class AppException(Exception):
    def __init__(self, code: str = ResponseCode.UN_ERROR.code, info: str | None = None, message: str | None = None):
        self.code = code
        self.info = info
        self.message = message or info
        super().__init__(self.message)


class AuthenticationError(AppException):
    def __init__(self, info: str = "Authentication required"):
        super().__init__("0008", info)


class PermissionDeniedError(AppException):
    def __init__(self, info: str = "Permission denied"):
        super().__init__("0009", info)


class QuotaExceededError(AppException):
    def __init__(self, info: str = "Quota exceeded"):
        super().__init__("0007", info)


class ResourceNotFoundError(AppException):
    def __init__(self, info: str = "Resource not found"):
        super().__init__("0010", info)


class UpstreamError(AppException):
    def __init__(self, info: str = "Upstream request failed"):
        super().__init__("0011", info)


class RetryExhaustedError(UpstreamError):
    pass


class TaskConflictError(AppException):
    def __init__(self, info: str = "Task conflict"):
        super().__init__("0012", info)


def openai_error(message: str, error_type: str, code: str, status_code: int) -> tuple[int, dict]:
    return status_code, {"error": {"message": message, "type": error_type, "code": code}}
