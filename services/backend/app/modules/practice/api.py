import hashlib
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import AppError
from app.modules.identity.deps import CurrentPrincipal, TenantSession
from app.modules.platform.jobs import JOB_RECORD_REALTIME_USAGE
from app.modules.platform.queue import enqueue

router = APIRouter()

REALTIME_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
PROVIDER_TIMEOUT_SECONDS = 15.0


class RealtimeTokenReport(BaseModel):
    """Token buckets from the provider's `response.done.usage`, summed over the session."""

    text_in: int = Field(default=0, ge=0, le=50_000_000)
    text_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    audio_in: int = Field(default=0, ge=0, le=50_000_000)
    audio_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    text_out: int = Field(default=0, ge=0, le=50_000_000)
    audio_out: int = Field(default=0, ge=0, le=50_000_000)


class RealtimeUsageReport(BaseModel):
    session_ref: str = Field(min_length=1, max_length=120)
    input_seconds: float = Field(ge=0, le=28_800)
    output_seconds: float = Field(ge=0, le=28_800)
    provider: Literal["azure", "openai"] = "azure"
    model_id: str | None = Field(default=None, max_length=120)
    # Preferred: realtime bills per token. Seconds remain for clients that cannot see usage.
    tokens: RealtimeTokenReport | None = None


class RealtimeUsageAccepted(BaseModel):
    job_id: str
    accepted: bool


def _safety_identifier(user_id: str, salt: str) -> str:
    """Stable per-user pseudonym for provider abuse tooling; never the raw user id."""
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()


@router.post("/realtime/session")
async def create_realtime_session(principal: CurrentPrincipal) -> dict:
    """Mint a short-lived browser credential; standard provider keys never leave the server.

    The identity comes from the verified token, never from the request body — the body
    form let any caller mint provider credentials against someone else's identity.
    Per-user rate limiting belongs here once Upstash Redis is provisioned.
    """
    settings = get_settings()
    if not settings.openai_api_key or not settings.openai_safety_identifier_salt:
        raise AppError(
            "realtime_not_configured", "Realtime provider is not configured", status_code=503
        )

    body = {"session": {"type": "realtime", "model": settings.openai_realtime_model}}
    try:
        async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT_SECONDS) as client:
            response = await client.post(
                REALTIME_CLIENT_SECRET_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "OpenAI-Safety-Identifier": _safety_identifier(
                        str(principal.user_id), settings.openai_safety_identifier_salt
                    ),
                },
            )
    except httpx.HTTPError as exc:
        raise AppError(
            "realtime_unreachable", "Realtime provider is unreachable", status_code=502
        ) from exc
    if response.is_error:
        raise AppError(
            "realtime_session_failed",
            "Realtime provider session creation failed",
            status_code=502,
        )
    return response.json()


@router.post("/realtime/usage", response_model=RealtimeUsageAccepted, status_code=202)
async def report_realtime_usage(
    principal: CurrentPrincipal, session: TenantSession, payload: RealtimeUsageReport
) -> RealtimeUsageAccepted:
    """Queue the metering write so a slow ledger never delays the end of a roleplay."""
    settings = get_settings()
    default_model = (
        settings.azure_voice_live_model
        if payload.provider == "azure"
        else settings.openai_realtime_model
    )
    result = await enqueue(
        session,
        workspace_id=principal.workspace_id,
        job_type=JOB_RECORD_REALTIME_USAGE,
        payload={
            "session_ref": payload.session_ref,
            "provider": payload.provider,
            "model_id": payload.model_id or default_model,
            "input_seconds": payload.input_seconds,
            "output_seconds": payload.output_seconds,
            "tokens": payload.tokens.model_dump() if payload.tokens else None,
        },
        idempotency_key=f"realtime-usage:{payload.session_ref}",
    )
    return RealtimeUsageAccepted(job_id=str(result.job_id), accepted=result.created)
