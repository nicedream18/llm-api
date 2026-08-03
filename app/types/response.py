"""Unified API response wrapper."""
from typing import Any, Optional
from pydantic import BaseModel

from app.types.enums import ResponseCode


class Response(BaseModel):
    code: str = ResponseCode.SUCCESS.code
    info: str = ResponseCode.SUCCESS.info
    data: Optional[Any] = None

    @staticmethod
    def success(data: Any = None) -> "Response":
        return Response(code=ResponseCode.SUCCESS.code, info=ResponseCode.SUCCESS.info, data=data)

    @staticmethod
    def fail(code: ResponseCode = ResponseCode.UN_ERROR, info: str = None) -> "Response":
        return Response(code=code.code, info=info or code.info, data=None)


class AppException(Exception):
    def __init__(self, code: str = ResponseCode.UN_ERROR.code, info: str = None, message: str = None):
        self.code = code
        self.info = info
        self.message = message or info
        super().__init__(self.message)
