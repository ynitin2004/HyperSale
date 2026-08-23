"""M0 job handlers.

Only one job exists at M0, and it exists because the M0 gate demands it: a real voice
session must leave a durable, costed usage record without blocking the request path.
"""
import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.jobs import JOB_RECORD_REALTIME_USAGE
from app.modules.platform.queue import ClaimedJob
from app.modules.platform.usage import EVENT_REALTIME_AUDIO, realtime_audio_cost, record_usage
from app.workers.registry import register

log = logging.getLogger("hypersale.worker.handlers")


class RealtimeUsagePayload(BaseModel):
    """Client-reported session shape. Treated as untrusted input, hence the bounds."""

    session_ref: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="openai", max_length=80)
    model_id: str | None = Field(default=None, max_length=120)
    # 8 hours is far beyond any roleplay; it exists to reject nonsense, not to allow it.
    input_seconds: float = Field(ge=0, le=28_800)
    output_seconds: float = Field(ge=0, le=28_800)


@register(JOB_RECORD_REALTIME_USAGE)
async def record_realtime_usage(session: AsyncSession, job: ClaimedJob) -> None:
    payload = RealtimeUsagePayload.model_validate(job.payload)
    cost = realtime_audio_cost(payload.input_seconds, payload.output_seconds)
    usage_id = await record_usage(
        session,
        workspace_id=job.workspace_id,
        event_type=EVENT_REALTIME_AUDIO,
        provider=payload.provider,
        model_id=payload.model_id,
        input_units=round(payload.input_seconds),
        output_units=round(payload.output_seconds),
        cost=cost,
        metadata={"session_ref": payload.session_ref, "source": "browser_report"},
        # Re-delivery of this job must not double-count the session.
        dedupe_key=f"realtime:{payload.session_ref}",
    )
    if cost.rate_missing:
        log.warning(
            "usage recorded without a configured rate",
            extra={"usage_event_id": str(usage_id), "session_ref": payload.session_ref},
        )
