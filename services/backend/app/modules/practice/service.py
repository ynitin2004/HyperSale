"""Practice session lifecycle and the server-authoritative transcript (D29).

Status machine: created -> connecting -> live -> ended | interrupted | failed.
`ended` means the rep or the cap hung up; `interrupted` means the call was lost (provider
closed, api restart) and the partial transcript was kept. Both lead to a report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.modules.catalog import service as catalog
from app.modules.identity.service import ROLE_MANAGER, Principal
from app.modules.practice.models import PracticeSession, TranscriptTurn

LIVE_STATUSES = ("connecting", "live")
FINAL_STATUSES = ("ended", "interrupted", "failed")


@dataclass(frozen=True)
class TurnView:
    idx: int
    speaker: str
    text: str
    start_ms: int
    end_ms: int


async def create_session(
    session: AsyncSession, principal: Principal, scenario_id: UUID, *, provider: str, cap_seconds: int
) -> PracticeSession:
    scenario = await catalog.get_scenario(session, scenario_id)
    persona = await catalog.get_persona_prompt(session, scenario.persona_id)
    row = PracticeSession(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        scenario_id=scenario.id,
        persona_id=persona.id,
        prompt_version=persona.prompt_version,
        rubric_version=scenario.rubric_version,
        status="created",
        provider=provider,
        cap_seconds=cap_seconds,
        timings={},
    )
    session.add(row)
    await session.flush()
    return row


async def get_session(
    session: AsyncSession, principal: Principal, session_id: UUID, *, for_update: bool = False
) -> PracticeSession:
    """A rep sees their own sessions; managers and owners see the whole workspace."""
    query = select(PracticeSession).where(
        PracticeSession.id == session_id,
        PracticeSession.workspace_id == principal.workspace_id,
    )
    if for_update:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None or (row.user_id != principal.user_id and not principal.has_role(ROLE_MANAGER)):
        # Same answer for "missing" and "not yours": no probing session ids.
        raise AppError("session_not_found", "Practice session not found", status_code=404)
    return row


async def get_session_by_id(session: AsyncSession, workspace_id: UUID, session_id: UUID) -> PracticeSession | None:
    """System-side lookup (live registry, scoring). Callers have already pinned the tenant."""
    return (
        await session.execute(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()


async def list_sessions(session: AsyncSession, principal: Principal, limit: int = 50) -> list[PracticeSession]:
    query = select(PracticeSession).where(PracticeSession.workspace_id == principal.workspace_id)
    if not principal.has_role(ROLE_MANAGER):
        query = query.where(PracticeSession.user_id == principal.user_id)
    rows = await session.execute(query.order_by(PracticeSession.created_at.desc()).limit(limit))
    return list(rows.scalars().all())


async def mark_connected(
    session: AsyncSession, workspace_id: UUID, session_id: UUID, *, session_ref: str,
    model_id: str, connect_ms: int,
) -> None:
    await session.execute(
        update(PracticeSession)
        .where(PracticeSession.id == session_id, PracticeSession.workspace_id == workspace_id)
        .values(
            status="live", session_ref=session_ref, model_id=model_id,
            connected_at=datetime.now(UTC),
            timings=PracticeSession.timings.op("||")(func.jsonb_build_object("connect_ms", int(connect_ms))),
        )
    )


async def upsert_turn(
    session: AsyncSession, workspace_id: UUID, session_id: UUID, *, item_id: str, speaker: str,
    text_: str, start_ms: int, end_ms: int,
) -> None:
    """Idempotent on (session, item_id): a provider re-sending a transcript cannot duplicate it."""
    if speaker not in ("rep", "buyer") or not text_.strip():
        return
    next_idx = select(text("coalesce(max(idx), -1) + 1")).select_from(TranscriptTurn).where(
        TranscriptTurn.session_id == session_id
    ).scalar_subquery()
    stmt = insert(TranscriptTurn).values(
        workspace_id=workspace_id, session_id=session_id, idx=next_idx, speaker=speaker,
        text=text_.strip(), start_ms=max(0, start_ms), end_ms=max(start_ms, end_ms), item_id=item_id,
    ).on_conflict_do_update(
        constraint="uq_transcript_turns_item",
        set_={"text": text_.strip(), "end_ms": max(start_ms, end_ms)},
    )
    await session.execute(stmt)


MAX_START_SHIFT_MS = 30_000


async def apply_turn_starts(session: AsyncSession, session_id: UUID, starts: dict[str, int]) -> int:
    """Correct start times from browser-observed VAD/response events (D32).

    Only timing moves: the text stays exactly what the api received from the provider, so
    D13's evidence checks are unaffected. A start may only move earlier than the server's
    estimate (transcripts arrive after speech), and by a bounded amount. One set-based
    statement: per-turn round trips over the pooler blew the < 1 s metrics budget."""
    items = list(starts.items())[:1000]
    if not items:
        return 0
    result = await session.execute(
        text("""
            UPDATE transcript_turns t SET start_ms = s.start
            FROM unnest(CAST(:items AS text[]), CAST(:starts AS int[])) AS s(item_id, start)
            WHERE t.session_id = :sid AND t.item_id = s.item_id
              AND s.start >= 0 AND s.start <= t.start_ms AND t.start_ms - s.start <= :max_shift
        """),
        {"items": [k[:80] for k, _ in items], "starts": [int(v) for _, v in items],
         "sid": str(session_id), "max_shift": MAX_START_SHIFT_MS},
    )
    return result.rowcount or 0


async def renumber_turns(session: AsyncSession, session_id: UUID) -> None:
    """Provider events arrive out of order (a rep's transcript can finish after the buyer
    starts answering), so the final order is by start time, assigned once at the end."""
    await session.execute(
        text("""
            UPDATE transcript_turns t SET idx = o.rn - 1
            FROM (SELECT id, row_number() OVER (ORDER BY start_ms, created_at) AS rn
                  FROM transcript_turns WHERE session_id = :sid) o
            WHERE t.id = o.id
        """),
        {"sid": str(session_id)},
    )


async def get_transcript(session: AsyncSession, session_id: UUID) -> list[TurnView]:
    rows = await session.execute(
        select(TranscriptTurn)
        .where(TranscriptTurn.session_id == session_id)
        .order_by(TranscriptTurn.idx, TranscriptTurn.start_ms)
    )
    return [TurnView(t.idx, t.speaker, t.text, t.start_ms, t.end_ms) for t in rows.scalars().all()]


async def mark_ended(
    session: AsyncSession, row: PracticeSession, *, status: str, reason: str, timings: dict
) -> None:
    now = datetime.now(UTC)
    row.status = status
    row.end_reason = reason[:40]
    row.ended_at = now
    if row.connected_at is not None:
        row.duration_ms = int((now - row.connected_at).total_seconds() * 1000)
    row.timings = {**(row.timings or {}), **timings}
    await session.flush()


async def record_recording_chunk(
    session: AsyncSession, row: PracticeSession, *, seq: int, size: int, mime: str | None
) -> None:
    row.recording_chunks = max(row.recording_chunks, seq + 1)
    row.recording_bytes = (row.recording_bytes or 0) + size
    if mime and not row.recording_mime:
        row.recording_mime = mime[:80]
    await session.flush()


async def list_timings(session: AsyncSession, workspace_id: UUID, limit: int = 200) -> list[dict]:
    rows = await session.execute(
        select(PracticeSession.timings)
        .where(PracticeSession.workspace_id == workspace_id, PracticeSession.status.in_(FINAL_STATUSES))
        .order_by(PracticeSession.created_at.desc())
        .limit(limit)
    )
    return [t or {} for t in rows.scalars().all()]
