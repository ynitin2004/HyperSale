import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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
from app.modules.practice.live import registry as live_registry
from app.modules.practice.live import sweep_orphans
from app.telemetry import setup_telemetry

log = logging.getLogger("hypersale.api")
ORPHAN_SWEEP_TIMEOUT_SECONDS = 5.0


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
    # D29: no socket survives a restart, so sessions left live are closed out now.
    try:
        # Bounded: a slow or unreachable database must not stop the api booting.
        swept = await asyncio.wait_for(sweep_orphans(), timeout=ORPHAN_SWEEP_TIMEOUT_SECONDS)
        if swept:
            log.warning("closed orphaned live sessions", extra={"count": swept})
    except Exception:  # noqa: BLE001 - a sweep failure must not stop the api booting
        log.warning("orphan sweep skipped", exc_info=True)
    try:
        yield
    finally:
        await live_registry.shutdown()
        await dispose_engine()


app = FastAPI(title="HyperSale API", version="0.0.1", lifespan=lifespan)
app.middleware("http")(correlation_id_middleware)
# The SPA and API are separate origins in dev (5173 vs 8000) and may be in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-Workspace-Id", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
app.add_exception_handler(AppError, app_error)
app.add_exception_handler(HTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(Exception, unhandled_error)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness only. Readiness, which touches the database, is /api/v1/ready."""
    return {"status": "ok", "request_id": request.state.request_id}
