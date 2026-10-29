"""Job handlers.

`platform.record_realtime_usage` meters client-reported voice usage (the M0 path, now a
fallback under D29); `scoring.score_report` is FLOW chain C, the report pipeline.
"""
import logging
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.scorer import build_fallback_scorer, build_scorer
from app.db.session import tenant_session
from app.modules.platform.jobs import JOB_RECORD_REALTIME_USAGE
from app.modules.platform.queue import ClaimedJob
from app.modules.platform.usage import (
    EVENT_REALTIME_AUDIO,
    RealtimeTokens,
    realtime_audio_cost,
    realtime_token_cost,
    record_usage,
)
from app.modules.scoring import service as scoring_service
from app.modules.scoring.service import JOB_SCORE_REPORT
from app.workers.registry import register

log = logging.getLogger("hypersale.worker.handlers")


class RealtimeTokenPayload(BaseModel):
    text_in: int = Field(default=0, ge=0, le=50_000_000)
    text_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    audio_in: int = Field(default=0, ge=0, le=50_000_000)
    audio_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    text_out: int = Field(default=0, ge=0, le=50_000_000)
    audio_out: int = Field(default=0, ge=0, le=50_000_000)


class RealtimeUsagePayload(BaseModel):
    """Client-reported session shape. Treated as untrusted input, hence the bounds."""

    session_ref: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="openai", max_length=80)
    model_id: str | None = Field(default=None, max_length=120)
    # 8 hours is far beyond any roleplay; it exists to reject nonsense, not to allow it.
    input_seconds: float = Field(ge=0, le=28_800)
    output_seconds: float = Field(ge=0, le=28_800)
    # When present the token path prices the session; seconds become descriptive only.
    tokens: RealtimeTokenPayload | None = None


@register(JOB_RECORD_REALTIME_USAGE)
async def record_realtime_usage(session: AsyncSession, job: ClaimedJob) -> None:
    payload = RealtimeUsagePayload.model_validate(job.payload)
    metadata: dict = {"session_ref": payload.session_ref, "source": "browser_report"}
    if payload.tokens is not None:
        tokens = RealtimeTokens(**payload.tokens.model_dump())
        cost = realtime_token_cost(tokens)
        input_units, output_units = tokens.input_total, tokens.output_total
        metadata.update(
            unit="tokens",
            tokens=payload.tokens.model_dump(),
            input_seconds=payload.input_seconds,
            output_seconds=payload.output_seconds,
        )
    else:
        cost = realtime_audio_cost(payload.input_seconds, payload.output_seconds)
        input_units, output_units = round(payload.input_seconds), round(payload.output_seconds)
        metadata["unit"] = "seconds"
    usage_id = await record_usage(
        session,
        workspace_id=job.workspace_id,
        event_type=EVENT_REALTIME_AUDIO,
        provider=payload.provider,
        model_id=payload.model_id,
        input_units=input_units,
        output_units=output_units,
        cost=cost,
        metadata=metadata,
        # Re-delivery of this job must not double-count the session.
        dedupe_key=f"realtime:{payload.session_ref}",
    )
    if cost.rate_missing:
        log.warning(
            "usage recorded without a configured rate",
            extra={"usage_event_id": str(usage_id), "session_ref": payload.session_ref},
        )


@register(JOB_SCORE_REPORT)
async def score_report(session: AsyncSession, job: ClaimedJob) -> None:
    """FLOW chain C. Retries come from the queue (max 3); the last failure is user-visible."""
    report_id = UUID(job.payload["report_id"])
    ended_at = job.payload.get("ended_at")
    try:
        report = await scoring_service.score_report(
            session, build_scorer(), workspace_id=job.workspace_id, report_id=report_id,
            ended_at=datetime.fromisoformat(ended_at) if ended_at else None,
            fallback=build_fallback_scorer(),
        )
    except Exception as exc:
        if job.is_final_attempt:
            # The job's own transaction rolls back, so the failure is written separately.
            async with tenant_session(job.workspace_id) as tx:
                await scoring_service.mark_failed(tx, job.workspace_id, report_id,
                                                  f"{type(exc).__name__}: {exc}")
        raise
    log.info("report scored", extra={"report_id": str(report_id), "status": report.status,
                                     "timings": report.timings})
