"""One error envelope for the whole API: {"error": {"code", "message", "request_id"}}.

Every handler returns the same shape so the generated client has a single error type and
every failure is traceable back to a log line by request id.
"""
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Starlette's class is the base of FastAPI's, so one handler covers framework 404s too.
from starlette.exceptions import HTTPException

from app.context import request_id_var


class AppError(Exception):
    """Expected, client-visible failure. Unexpected failures stay generic."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.headers = headers


class AuthError(AppError):
    def __init__(self, code: str = "unauthenticated", message: str = "Authentication failed") -> None:
        super().__init__(code, message, status_code=401, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    def __init__(self, message: str = "Insufficient role for this action") -> None:
        super().__init__("forbidden", message, status_code=403)


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", request_id_var.get())


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id(request)}
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content={"error": body}, headers=headers)


async def correlation_id_middleware(request: Request, call_next: Callable):
    incoming = request.headers.get("X-Request-ID", "")
    # A caller-supplied id is echoed for tracing but bounded so it cannot bloat logs.
    resolved = incoming[:120] if incoming else str(uuid4())
    request.state.request_id = resolved
    token = request_id_var.set(resolved)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = resolved
    return response


async def app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        headers=exc.headers,
    )


async def http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    return error_response(
        request,
        status_code=exc.status_code,
        code=f"http_{exc.status_code}",
        message=str(exc.detail),
        headers=getattr(exc, "headers", None),
    )


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(
        request,
        status_code=422,
        code="invalid_request",
        message="Request validation failed",
        extra={"details": exc.errors()},
    )


async def unhandled_error(request: Request, _exc: Exception) -> JSONResponse:
    # Never leak internals; the request id is the bridge to the logged traceback.
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred",
    )
