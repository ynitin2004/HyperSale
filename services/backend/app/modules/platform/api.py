from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import ping
from app.modules.identity.deps import CurrentPrincipal, TenantSession, require_role
from app.modules.identity.service import ROLE_MANAGER, ROLE_OWNER, Principal
from app.modules.platform import audit
from app.modules.platform import workspace_settings as ws_settings
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
        "realtime_configured": settings.voice_provider == "stub" or bool(settings.azure_voice_live_api_key),
        "voice_provider": settings.voice_provider,
        "scoring_provider": settings.scoring_provider,
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


# ---------------------------------------------------------------- M4 settings and audit (D46, D47)


class WorkspaceSettingsIn(BaseModel):
    # None means "keep audio forever" / "no spend limit".
    audio_retention_days: int | None = Field(default=None, ge=1, le=3650)
    monthly_limit_microusd: int | None = Field(default=None, ge=0, le=100_000_000_000)
    record_roleplay_audio: bool = True


class WorkspaceSettingsOut(WorkspaceSettingsIn):
    month_spent_microusd: int
    can_edit: bool


class AuditEventOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    action: str
    target_type: str
    target_id: str | None
    detail: dict[str, Any]
    created_at: datetime


async def _settings_out(session: AsyncSession, principal: Principal) -> WorkspaceSettingsOut:
    view = await ws_settings.get(session, principal.workspace_id)
    return WorkspaceSettingsOut(**vars(view), can_edit=principal.has_role(ROLE_OWNER),
                                month_spent_microusd=await ws_settings.month_spend(session, principal.workspace_id))


@router.get("/workspace/settings", response_model=WorkspaceSettingsOut)
async def get_workspace_settings(principal: CurrentPrincipal, session: TenantSession) -> WorkspaceSettingsOut:
    """Every member reads it: the browser needs `record_roleplay_audio` before a call."""
    return await _settings_out(session, principal)


@router.put("/workspace/settings", response_model=WorkspaceSettingsOut)
async def put_workspace_settings(body: WorkspaceSettingsIn, principal: CurrentPrincipal,
                                 session: TenantSession) -> WorkspaceSettingsOut:
    principal.require_role(ROLE_OWNER)
    await ws_settings.update(session, principal.workspace_id, principal.user_id,
                             ws_settings.SettingsView(**body.model_dump()))
    return await _settings_out(session, principal)


@router.get("/audit", response_model=list[AuditEventOut])
async def audit_log(principal: ManagerPrincipal, session: TenantSession,
                    limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEventOut]:
    return [AuditEventOut(id=e.id, actor_user_id=e.actor_user_id, action=e.action, target_type=e.target_type,
                          target_id=e.target_id, detail=e.detail, created_at=e.created_at)
            for e in await audit.recent(session, principal.workspace_id, limit)]
