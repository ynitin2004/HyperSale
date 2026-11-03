"""Audio retention (D46): delete recordings older than the workspace's window; keep the transcript.

Storage goes first, then the row. A crash in between leaves a row that still says "recorded" with
no objects behind it, so the retry lists nothing, deletes nothing, and finishes the row. The other
order would mark audio deleted that is still sitting in the bucket.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage import RecordingStore
from app.db.models import Workspace
from app.modules.platform import audit
from app.modules.platform import workspace_settings as ws_settings
from app.modules.platform.queue import enqueue
from app.modules.practice.models import PracticeSession

JOB_RETENTION_SWEEP = "practice.retention_sweep"
SWEEP_BATCH = 200


@dataclass(frozen=True)
class SweepResult:
    sessions: int
    objects: int


async def schedule_daily(dispatch: AsyncSession, now: datetime | None = None) -> int:
    """Enqueue today's sweep for every workspace; the date in the key makes it once a UTC day.

    Runs on the worker's dispatch session (the BYPASSRLS role, like claiming jobs), because it is
    the one step that must see every workspace. The sweep itself runs pinned to one tenant.
    """
    day = (now or datetime.now(UTC)).date().isoformat()
    created = 0
    for workspace_id in (await dispatch.execute(select(Workspace.id))).scalars().all():
        result = await enqueue(dispatch, workspace_id=workspace_id, job_type=JOB_RETENTION_SWEEP,
                               payload={}, idempotency_key=f"retention:{day}", max_attempts=3)
        created += int(result.created)
    return created


async def sweep(session: AsyncSession, store: RecordingStore, workspace_id: UUID,
                now: datetime | None = None) -> SweepResult:
    days = (await ws_settings.get(session, workspace_id)).audio_retention_days
    if days is None:
        return SweepResult(0, 0)
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = (await session.execute(
        select(PracticeSession).where(
            PracticeSession.workspace_id == workspace_id,
            PracticeSession.recording_deleted_at.is_(None),
            PracticeSession.recording_chunks > 0,
            func.coalesce(PracticeSession.ended_at, PracticeSession.created_at) < cutoff,
        ).order_by(PracticeSession.created_at).limit(SWEEP_BATCH).with_for_update(skip_locked=True)
    )).scalars().all()
    objects = 0
    for row in rows:
        keys = await store.list_session(workspace_id, row.id)
        await store.delete(keys)
        objects += len(keys)
        await audit.record(session, workspace_id, actor=None, action="recording.deleted",
                           target_type="practice_session", target_id=row.id,
                           detail={"objects": len(keys), "bytes": row.recording_bytes, "retention_days": days,
                                   "kind": row.kind})
        row.recording_deleted_at = datetime.now(UTC)
        row.recording_chunks = 0
    await session.flush()
    return SweepResult(len(rows), objects)
