from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.session import ping
from app.modules.identity.deps import CurrentPrincipal, TenantSession, require_role
from app.modules.identity.service import ROLE_MANAGER, Principal
from app.modules.platform.usage import usage_summary

router = APIRouter()

ManagerPrincipal = Annotated[Principal, Depends(require_role(ROLE_MANAGER))]


@router.get("/config")
async def public_config(request: Request) -> dict[str, Any]:
    """Safe browser configuration; provider credentials are never returned."""
    settings = get_settings()
    return {
        "environment": settings.app_env,
        "auth_configured": settings.auth_configured,
        "realtime_configured": bool(settings.azure_voice_live_api_key or settings.openai_api_key),
        "request_id": request.state.request_id,
    }


@router.get("/ready")
async def readiness() -> JSONResponse:
    """Readiness differs from liveness: this one fails when the database is unreachable."""
    try:
        await ping()
    except Exception:  # noqa: BLE001 - any driver error means "not ready"
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": False})
    return JSONResponse(status_code=200, content={"status": "ok", "database": True})


@router.get("/usage/summary")
async def workspace_usage(
    principal: ManagerPrincipal,
    session: TenantSession,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await usage_summary(session, principal.workspace_id, since)
    return {
        "workspace_id": str(principal.workspace_id),
        "since": since.isoformat(),
        "total_cost_microusd": sum(row["cost_microusd"] or 0 for row in rows),
        # True when any bucket was priced with an unmeasured rate: the total is a floor.
        "rate_missing": any(row["rate_missing"] for row in rows),
        "by_event_type": rows,
    }


@router.get("/whoami")
async def whoami(principal: CurrentPrincipal) -> dict[str, str]:
    """Cheap authenticated probe used by the web shell to confirm the session works."""
    return {"user_id": str(principal.user_id), "workspace_id": str(principal.workspace_id)}
