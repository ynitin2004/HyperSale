import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.api.router import api_router
from app.config import get_settings
from app.db.session import dispose_engine
from app.errors import (
    AppError,
    app_error,
    correlation_id_middleware,
    http_error,
    unhandled_error,
    validation_error,
)
from app.telemetry import setup_telemetry

log = logging.getLogger("hypersale.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    enabled = setup_telemetry(app)
    settings = get_settings()
    log.info(
        "api starting",
        extra={
            "environment": settings.app_env,
            "auth_configured": settings.auth_configured,
            "telemetry": enabled,
        },
    )
    try:
        yield
    finally:
        await dispose_engine()


app = FastAPI(title="HyperSale API", version="0.0.1", lifespan=lifespan)
app.middleware("http")(correlation_id_middleware)
app.add_exception_handler(AppError, app_error)
app.add_exception_handler(HTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(Exception, unhandled_error)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness only. Readiness, which touches the database, is /api/v1/ready."""
    return {"status": "ok", "request_id": request.state.request_id}
