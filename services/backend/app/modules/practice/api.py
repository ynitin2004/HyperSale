"""Practice HTTP surface (FLOW chain B).

Session flow: POST /sessions -> POST /sessions/{id}/connect (SDP relay, D29) -> live call
-> POST /sessions/{id}/end -> report. The browser never receives a provider credential:
it sends an SDP offer and gets an SDP answer, and media flows browser<->Azure directly.
"""
import hashlib
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.adapters.storage import build_recording_store
from app.adapters.voice import VoiceProviderError, build_voice_provider
from app.config import get_settings
from app.db.session import tenant_session
from app.errors import AppError
from app.modules.catalog import service as catalog
from app.modules.identity.deps import CurrentPrincipal, TenantSession
from app.modules.platform.jobs import JOB_RECORD_REALTIME_USAGE
from app.modules.platform.queue import enqueue
from app.modules.practice import live
from app.modules.practice import service as practice
from app.modules.practice.models import PracticeSession

router = APIRouter()


# ---------------------------------------------------------------- schemas


class CreateSessionIn(BaseModel):
    scenario_id: UUID


class SessionOut(BaseModel):
    id: UUID
    scenario_id: UUID
    status: str
    provider: str
    cap_seconds: int
    prompt_version: str
    rubric_version: str
    end_reason: str | None
    duration_ms: int | None
    recording_chunks: int
    recording_mime: str | None
    recorder_offset_ms: int | None
    created_at: str
    user_id: UUID | None = None
    report_id: UUID | None = None
    report_status: str | None = None
    overall: float | None = None


class ConnectIn(BaseModel):
    sdp_offer: str | None = Field(default=None, max_length=50_000)


class ConnectOut(BaseModel):
    mode: Literal["webrtc", "stub"]
    sdp_answer: str | None
    session_ref: str
    cap_seconds: int
    connect_ms: int


class EndIn(BaseModel):
    reason: Literal["rep_ended", "rep_left", "client_error"] = "rep_ended"
    recorder_offset_ms: int | None = Field(default=None, ge=-60_000, le=60_000)
    # Voice Live delivers usage and VAD/response-start events only on the browser's data
    # channel, never on the api-held socket (measured 2026-10-29, D32). The browser reports
    # them at hang-up; the api bounds them and labels the ledger row's source.
    usage: "RealtimeTokenReport | None" = None
    turn_starts: dict[str, int] | None = Field(default=None, max_length=1000)


class EndOut(BaseModel):
    report_id: UUID | None
    status: str


class TurnOut(BaseModel):
    idx: int
    speaker: Literal["rep", "buyer"]
    text: str
    start_ms: int
    end_ms: int


def _session_out(row: PracticeSession, report=None) -> SessionOut:
    return SessionOut(
        id=row.id, scenario_id=row.scenario_id, status=row.status, provider=row.provider,
        cap_seconds=row.cap_seconds, prompt_version=row.prompt_version,
        rubric_version=row.rubric_version, end_reason=row.end_reason, duration_ms=row.duration_ms,
        recording_chunks=row.recording_chunks, recording_mime=row.recording_mime,
        recorder_offset_ms=row.recorder_offset_ms, created_at=row.created_at.isoformat(),
        user_id=row.user_id, report_id=report.id if report else None, report_status=report.status if report else None,
        overall=float(report.overall) if report is not None and report.overall is not None else None,
    )


def _user_ref(user_id: UUID) -> str:
    salt = get_settings().openai_safety_identifier_salt or "hypersale"
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()


# ---------------------------------------------------------------- sessions


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    body: CreateSessionIn, principal: CurrentPrincipal, session: TenantSession
) -> SessionOut:
    settings = get_settings()
    row = await practice.create_session(
        session, principal, body.scenario_id, provider=settings.voice_provider,
        cap_seconds=settings.session_cap_seconds,
    )
    return _session_out(row)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    principal: CurrentPrincipal, session: TenantSession, user_id: UUID | None = None
) -> list[SessionOut]:
    """Reps see their own; managers see everyone's, or one member's with `user_id` (D39)."""
    from app.modules.scoring import service as scoring

    rows = await practice.list_sessions(session, principal, user_id=user_id)
    reports = await scoring.reports_for_sessions(session, [r.id for r in rows])
    return [_session_out(r, reports.get(r.id)) for r in rows]


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> SessionOut:
    from app.modules.scoring import service as scoring

    row = await practice.get_session(session, principal, session_id)
    return _session_out(row, await scoring.report_for_session(session, session_id))


@router.post("/sessions/{session_id}/connect", response_model=ConnectOut)
async def connect(
    session_id: UUID, body: ConnectIn, principal: CurrentPrincipal, session: TenantSession
) -> ConnectOut:
    started = time.perf_counter()
    row = await practice.get_session(session, principal, session_id)
    if row.user_id != principal.user_id:
        raise AppError("forbidden", "Only the rep who started a session can connect it", status_code=403)
    persona = await catalog.get_persona_prompt(session, row.persona_id)

    # Writes go through short tenant transactions of their own: the request session stays
    # read-only, so it never holds a row lock that the live call's writers would wait on,
    # and its transaction-local tenant GUCs are never lost to a mid-request commit.
    async with tenant_session(principal.workspace_id, principal.user_id) as tx:
        # Atomic guard: exactly one connect per session, even with a double-clicked button.
        claimed = await tx.execute(
            update(PracticeSession)
            .where(PracticeSession.id == session_id, PracticeSession.status == "created")
            .values(status="connecting")
            .returning(PracticeSession.id)
        )
        if claimed.scalar_one_or_none() is None:
            raise AppError("session_not_connectable", f"Session is {row.status}", status_code=409)

    provider = build_voice_provider()
    try:
        call = await provider.open_call(
            sdp_offer=body.sdp_offer, instructions=persona.instructions, voice=persona.voice,
            user_ref=_user_ref(principal.user_id),
        )
    except VoiceProviderError as exc:
        async with tenant_session(principal.workspace_id, principal.user_id) as tx:
            await tx.execute(
                update(PracticeSession).where(PracticeSession.id == session_id)
                .values(status="failed", end_reason="connect_failed")
            )
        raise AppError("voice_connect_failed", str(exc), status_code=502) from exc

    connect_ms = int((time.perf_counter() - started) * 1000)
    async with tenant_session(principal.workspace_id, principal.user_id) as tx:
        await practice.mark_connected(
            tx, principal.workspace_id, session_id, session_ref=call.session.session_ref,
            model_id=call.session.model_id, connect_ms=connect_ms,
        )
    live.registry.start(live.LiveSession(
        session_id=session_id, workspace_id=principal.workspace_id, user_id=principal.user_id,
        call=call, cap_seconds=row.cap_seconds, connect_ms=connect_ms,
    ))
    return ConnectOut(mode=call.session.mode, sdp_answer=call.session.sdp_answer,
                      session_ref=call.session.session_ref, cap_seconds=row.cap_seconds,
                      connect_ms=connect_ms)


@router.post("/sessions/{session_id}/end", response_model=EndOut)
async def end_session(
    session_id: UUID, body: EndIn, principal: CurrentPrincipal, session: TenantSession
) -> EndOut:
    from app.modules.scoring import service as scoring

    row = await practice.get_session(session, principal, session_id)
    if body.recorder_offset_ms is not None:
        async with tenant_session(principal.workspace_id, principal.user_id) as tx:
            await tx.execute(
                update(PracticeSession).where(PracticeSession.id == session_id)
                .values(recorder_offset_ms=body.recorder_offset_ms)
            )

    report_id = await live.registry.end(
        session_id, body.reason,
        client_usage=body.usage.model_dump() if body.usage else None,
        turn_starts=body.turn_starts,
    )
    if report_id is None:
        existing = await scoring.report_for_session(session, session_id)
        if existing is not None:
            return EndOut(report_id=existing.id, status=existing.status)
        if row.status in ("created", "connecting"):
            await session.execute(
                update(PracticeSession).where(PracticeSession.id == session_id)
                .values(status="failed", end_reason="never_connected")
            )
            return EndOut(report_id=None, status="failed")
        # Live in the DB but not in this process: an api restart lost the socket (D29).
        report_id = await live.finalize_session(
            workspace_id=principal.workspace_id, user_id=row.user_id, session_id=session_id,
            reason="api_restart", usage=None,
        )
    return EndOut(report_id=report_id, status="pending")


@router.get("/sessions/{session_id}/transcript", response_model=list[TurnOut])
async def transcript(session_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> list[TurnOut]:
    await practice.get_session(session, principal, session_id)
    return [TurnOut(idx=t.idx, speaker=t.speaker, text=t.text, start_ms=t.start_ms, end_ms=t.end_ms)
            for t in await practice.get_transcript(session, session_id)]


# ---------------------------------------------------------------- recording (D31)


@router.put("/sessions/{session_id}/recording/{seq}", status_code=204)
async def upload_chunk(
    session_id: UUID, seq: Annotated[int, Path(ge=0, le=9999)], request: Request,
    principal: CurrentPrincipal, session: TenantSession,
) -> Response:
    row = await practice.get_session(session, principal, session_id)
    if row.user_id != principal.user_id:
        raise AppError("forbidden", "Only the rep can upload this recording", status_code=403)
    data = await request.body()
    if not data:
        raise AppError("empty_chunk", "Recording chunk is empty", status_code=400)
    if len(data) > get_settings().recording_max_chunk_bytes:
        raise AppError("chunk_too_large", "Recording chunk too large", status_code=413)
    await build_recording_store().put_chunk(principal.workspace_id, session_id, seq, data)
    await practice.record_recording_chunk(session, row, seq=seq, size=len(data),
                                          mime=request.headers.get("content-type"))
    return Response(status_code=204)


@router.get("/sessions/{session_id}/recording")
async def download_recording(session_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> Response:
    row = await practice.get_session(session, principal, session_id)
    if not row.recording_chunks:
        raise AppError("recording_unavailable", "No recording for this session", status_code=404)
    data = await build_recording_store().read_all(principal.workspace_id, session_id, row.recording_chunks)
    if not data:
        raise AppError("recording_unavailable", "No recording for this session", status_code=404)
    mime = (row.recording_mime or "audio/webm").split(";")[0]
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------- M0 fallback metering


class RealtimeTokenReport(BaseModel):
    """Token buckets from the provider's `response.done.usage`, summed over the session."""

    text_in: int = Field(default=0, ge=0, le=50_000_000)
    text_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    audio_in: int = Field(default=0, ge=0, le=50_000_000)
    audio_in_cached: int = Field(default=0, ge=0, le=50_000_000)
    text_out: int = Field(default=0, ge=0, le=50_000_000)
    audio_out: int = Field(default=0, ge=0, le=50_000_000)
    responses: int = Field(default=0, ge=0, le=10_000)


class RealtimeUsageReport(BaseModel):
    session_ref: str = Field(min_length=1, max_length=120)
    input_seconds: float = Field(ge=0, le=28_800)
    output_seconds: float = Field(ge=0, le=28_800)
    provider: Literal["azure", "openai"] = "azure"
    model_id: str | None = Field(default=None, max_length=120)
    tokens: RealtimeTokenReport | None = None


class RealtimeUsageAccepted(BaseModel):
    job_id: str
    accepted: bool


@router.post("/realtime/usage", response_model=RealtimeUsageAccepted, status_code=202)
async def report_realtime_usage(
    principal: CurrentPrincipal, session: TenantSession, payload: RealtimeUsageReport
) -> RealtimeUsageAccepted:
    """Client-reported usage, kept for spikes and clients without a brokered socket.
    Brokered sessions are metered server-side from the socket (D29) under the same
    dedupe key, so a client report can never double-count them."""
    settings = get_settings()
    result = await enqueue(
        session,
        workspace_id=principal.workspace_id,
        job_type=JOB_RECORD_REALTIME_USAGE,
        payload={
            "session_ref": payload.session_ref,
            "provider": payload.provider,
            "model_id": payload.model_id or settings.azure_voice_live_model,
            "input_seconds": payload.input_seconds,
            "output_seconds": payload.output_seconds,
            "tokens": payload.tokens.model_dump() if payload.tokens else None,
        },
        idempotency_key=f"realtime-usage:{payload.session_ref}",
    )
    return RealtimeUsageAccepted(job_id=str(result.job_id), accepted=result.created)


EndIn.model_rebuild()
