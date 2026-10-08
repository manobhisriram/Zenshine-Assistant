"""Application errors and their HTTP mapping."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger("errors")


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Something went wrong."

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.headers = headers or {}


class BadRequest(AppError):
    status_code, code, message = 400, "bad_request", "The request could not be processed."


class Unauthorized(AppError):
    status_code, code, message = 401, "unauthorized", "Missing or invalid credentials."


class NotFound(AppError):
    status_code, code, message = 404, "not_found", "Resource not found."


class RateLimited(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests. Please slow down."


class UpstreamUnavailable(AppError):
    status_code, code, message = 503, "upstream_unavailable", "A dependency is temporarily unavailable."


def _body(code: str, message: str, request: Request) -> dict:
    return {"error": {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, request), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()]
        return JSONResponse(
            _body("validation_error", f"Invalid request: {', '.join(sorted(set(fields)))}", request), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _body("http_error", str(exc.detail), request), status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", path=request.url.path, error_type=type(exc).__name__, exc_info=exc)
        return JSONResponse(_body("internal_error", "Something went wrong.", request), status_code=500)
