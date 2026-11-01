"""FLOW chain D: an uploaded call becomes a transcript, then runs the same chain C as a roleplay.

The upload is a `practice_sessions` row of kind `review`, so transcripts, recordings, reports and
evidence all reuse the roleplay path (D43). `process` runs in one job transaction: a worker killed
mid-job rolls everything back and the retry starts clean, with no duplicate turns, report or usage.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.models import TRANSCRIBE_MICROUSD_PER_HOUR
from app.adapters.storage import build_recording_store
from app.adapters.transcription import Phrase, Transcriber, Transcript
from app.config import get_settings
from app.errors import AppError
from app.modules.identity.service import Principal
from app.modules.platform.queue import enqueue
from app.modules.platform.usage import EVENT_TRANSCRIPTION, UsageCost, record_usage
from app.modules.practice import service as practice
from app.modules.practice.models import KIND_REVIEW, PracticeSession
from app.modules.scoring import service as scoring

JOB_REVIEW_TRANSCRIBE = "review.transcribe"
STATUS_UPLOADING = "uploading"
STATUS_TRANSCRIBING = "transcribing"
MS_PER_HOUR = 3_600_000


class OneSpeakerOnly(Exception):
    """Scoring needs both sides of the call; retrying the same audio cannot change that."""


def to_turns(phrases: Sequence[Phrase], *, rep_speaks_first: bool) -> list[tuple[str, str, int, int]]:
    """Name the anonymous speakers and join each run of one speaker into a turn."""
    order = list(dict.fromkeys(p.speaker for p in phrases))
    if len(order) < 2:
        raise OneSpeakerOnly
    first, second = ("rep", "buyer") if rep_speaks_first else ("buyer", "rep")
    roles = {speaker: first if speaker == order[0] else second for speaker in order}
    turns: list[tuple[str, str, int, int]] = []
    for p in phrases:
        role = roles[p.speaker]
        if turns and turns[-1][0] == role:
            _, text, start, _ = turns[-1]
            turns[-1] = (role, f"{text} {p.text}", start, p.end_ms)
        else:
            turns.append((role, p.text, p.start_ms, p.end_ms))
    return turns


async def create_review(
    session: AsyncSession, principal: Principal, scenario_id: UUID, *, rep_speaks_first: bool, consent: bool
) -> PracticeSession:
    if not consent:
        raise AppError("consent_required", "Confirm you have permission to upload this call", status_code=422)
    row = await practice.create_session(session, principal, scenario_id, provider="upload", cap_seconds=0)
    row.kind = KIND_REVIEW
    row.status = STATUS_UPLOADING
    row.consent_at = datetime.now(UTC)
    row.timings = {"rep_speaks_first": rep_speaks_first}
    await session.flush()
    return row


async def submit(session: AsyncSession, principal: Principal, session_id: UUID) -> PracticeSession:
    row = await practice.get_session(session, principal, session_id)
    if row.kind != KIND_REVIEW or row.user_id != principal.user_id:
        raise AppError("forbidden", "Only the uploader can submit this call", status_code=403)
    if not row.recording_chunks:
        raise AppError("no_audio", "Upload the audio first", status_code=409)
    if row.recording_bytes > get_settings().review_max_bytes:
        raise AppError("upload_too_large", "This recording is too large", status_code=413)
    claimed = await session.execute(
        update(PracticeSession)
        .where(PracticeSession.id == session_id, PracticeSession.status == STATUS_UPLOADING)
        .values(status=STATUS_TRANSCRIBING).returning(PracticeSession.id)
    )
    if claimed.scalar_one_or_none() is None:
        raise AppError("already_submitted", f"Call is {row.status}", status_code=409)
    await enqueue(session, workspace_id=row.workspace_id, job_type=JOB_REVIEW_TRANSCRIBE,
                  payload={"session_id": str(session_id)}, idempotency_key=f"review:{session_id}", max_attempts=3)
    await session.refresh(row)
    return row


async def _record_cost(session: AsyncSession, row: PracticeSession, transcript: Transcript) -> None:
    await record_usage(
        session, workspace_id=row.workspace_id, event_type=EVENT_TRANSCRIPTION,
        provider=transcript.provider, model_id=transcript.model_id, input_units=transcript.duration_ms,
        cost=UsageCost(transcript.duration_ms * TRANSCRIBE_MICROUSD_PER_HOUR // MS_PER_HOUR, False),
        metadata={"unit": "ms", "practice_session_id": str(row.id)}, dedupe_key=f"transcribe:{row.id}",
    )


async def process(session: AsyncSession, transcriber: Transcriber, *, workspace_id: UUID, session_id: UUID) -> None:
    """Idempotent: stall recovery may re-deliver a finished job."""
    row = await practice.get_session_by_id(session, workspace_id, session_id)
    if row is None:
        raise LookupError(f"session {session_id} not found")
    if row.status != STATUS_TRANSCRIBING:
        return
    store = build_recording_store()
    audio = await store.read_all(workspace_id, session_id, row.recording_chunks)
    transcript = await transcriber.transcribe(audio, row.recording_mime)
    await _record_cost(session, row, transcript)
    try:
        turns = to_turns(transcript.phrases, rep_speaks_first=row.timings["rep_speaks_first"])
    except OneSpeakerOnly:
        await practice.mark_ended(session, row, status="failed", reason="one_speaker", timings={})
        return
    await practice.add_turns(session, row, turns)
    await practice.mark_ended(session, row, status="ended", reason="uploaded", timings={})
    row.duration_ms = transcript.duration_ms
    await scoring.create_report(
        session, workspace_id=workspace_id, session_id=session_id, rubric_version=row.rubric_version,
        turns=await practice.get_transcript(session, session_id), ended_at=datetime.now(UTC),
    )


async def mark_failed(session: AsyncSession, workspace_id: UUID, session_id: UUID) -> None:
    row = await practice.get_session_by_id(session, workspace_id, session_id)
    if row is not None:
        await practice.mark_ended(session, row, status="failed", reason="transcribe_failed", timings={})
