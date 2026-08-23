from collections.abc import Callable
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


async def correlation_id_middleware(request: Request, call_next: Callable):
    request.state.request_id = request.headers.get("X-Request-ID", str(uuid4()))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


async def unhandled_error(request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "request_id": request_id(request)}},
    )

