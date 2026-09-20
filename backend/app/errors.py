"""把业务错误、参数错误和框架错误转换为统一的 JSON 格式。"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


logger = logging.getLogger(__name__)


class ApiError(Exception):
    """业务代码通过这个异常指定 HTTP 状态码、错误代码和说明。"""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """由 main.py 调用一次，让整个应用使用同一套错误格式。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            422, "INVALID_REQUEST", "请求参数不正确，请检查提交内容"
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException):
        # 未知地址和不支持的请求方法也要使用统一格式。
        code, message = {
            404: ("NOT_FOUND", "请求的接口不存在"),
            405: ("METHOD_NOT_ALLOWED", "该接口不支持此请求方法"),
        }.get(exc.status_code, ("HTTP_ERROR", str(exc.detail)))
        return error_response(exc.status_code, code, message, exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        # 详细原因记录在后端日志中，响应只返回通用错误说明。
        logger.error(
            "Unhandled API error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return error_response(500, "INTERNAL_ERROR", "服务处理失败，请稍后重试")
