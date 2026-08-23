"""Durable job queue on Postgres `SELECT ... FOR UPDATE SKIP LOCKED`.

No broker: the database that already owns the truth also owns the work. Claims are
atomic, retries are bounded and backed off, and a crashed worker's jobs return to the
queue once their heartbeat goes stale.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.platform.jobs import JobState

MAX_ERROR_CHARS = 2000

_ENQUEUE = text("""
    INSERT INTO jobs (workspace_id, type, payload, idempotency_key, max_attempts, run_after)
    VALUES (
        :workspace_id, :type, CAST(:payload AS jsonb), :idempotency_key,
        :max_attempts, COALESCE(CAST(:run_after AS timestamptz), now())
    )
    ON CONFLICT (workspace_id, idempotency_key) DO NOTHING
    RETURNING id
""")

_FIND_EXISTING = text("""
    SELECT id FROM jobs WHERE workspace_id = :workspace_id AND idempotency_key = :idempotency_key
""")

# The CTE locks only rows this worker will take; SKIP LOCKED lets peers pass them by.
_CLAIM = text("""
    WITH claimed AS (
        SELECT id
        FROM jobs
        WHERE state = 'queued' AND run_after <= now()
        ORDER BY run_after
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    )
    UPDATE jobs AS j
    SET state = 'running',
        attempts = j.attempts + 1,
        locked_by = :worker_id,
        heartbeat_at = now(),
        updated_at = now()
    FROM claimed
    WHERE j.id = claimed.id
    RETURNING j.id, j.workspace_id, j.type, j.payload, j.attempts, j.max_attempts
""")

_SUCCEED = text("""
    UPDATE jobs
    SET state = 'succeeded', last_error = NULL, locked_by = NULL,
        heartbeat_at = NULL, updated_at = now()
    WHERE id = :job_id AND state = 'running'
    RETURNING id
""")

_FAIL = text("""
    UPDATE jobs
    SET state = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
        run_after = CASE
            WHEN attempts >= max_attempts THEN run_after
            ELSE now() + make_interval(secs => :backoff_seconds)
        END,
        last_error = :error, locked_by = NULL, heartbeat_at = NULL, updated_at = now()
    WHERE id = :job_id AND state = 'running'
    RETURNING state, attempts, max_attempts
""")

_HEARTBEAT = text("""
    UPDATE jobs SET heartbeat_at = now()
    WHERE id = ANY(CAST(:job_ids AS uuid[])) AND locked_by = :worker_id AND state = 'running'
""")

_REQUEUE_STALLED = text("""
    UPDATE jobs
    SET state = 'queued', locked_by = NULL, heartbeat_at = NULL,
        run_after = now(), updated_at = now()
    WHERE state = 'running'
      AND heartbeat_at IS NOT NULL
      AND heartbeat_at < now() - make_interval(secs => :stall_seconds)
    RETURNING id
""")


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    workspace_id: UUID
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int

    @property
    def is_final_attempt(self) -> bool:
        return self.attempts >= self.max_attempts


@dataclass(frozen=True)
class EnqueueResult:
    job_id: UUID
    created: bool


def backoff_seconds(attempts: int) -> int:
    """Deterministic exponential backoff. Deterministic so retry timing is testable."""
    settings = get_settings()
    if attempts < 1:
        return settings.job_backoff_base_seconds
    delay = settings.job_backoff_base_seconds * (2 ** (attempts - 1))
    return int(min(delay, settings.job_backoff_max_seconds))


async def enqueue(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    job_type: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
) -> EnqueueResult:
    """Insert a job, or return the existing one for the same idempotency key."""
    params = {
        "workspace_id": str(workspace_id),
        "type": job_type,
        "payload": json.dumps(payload or {}),
        "idempotency_key": idempotency_key,
        "max_attempts": max_attempts or get_settings().job_max_attempts,
        # asyncpg types this parameter as timestamptz from the cast, so it must be a
        # datetime; an ISO string would be rejected by the driver.
        "run_after": run_after,
    }
    inserted = (await session.execute(_ENQUEUE, params)).scalar_one_or_none()
    if inserted is not None:
        return EnqueueResult(job_id=inserted, created=True)

    existing = (
        await session.execute(
            _FIND_EXISTING,
            {"workspace_id": params["workspace_id"], "idempotency_key": idempotency_key},
        )
    ).scalar_one()
    return EnqueueResult(job_id=existing, created=False)


async def claim(
    session: AsyncSession, *, worker_id: str, batch_size: int = 1
) -> list[ClaimedJob]:
    result = await session.execute(_CLAIM, {"worker_id": worker_id, "batch_size": batch_size})
    return [
        ClaimedJob(
            id=row.id,
            workspace_id=row.workspace_id,
            type=row.type,
            payload=row.payload or {},
            attempts=row.attempts,
            max_attempts=row.max_attempts,
        )
        for row in result.all()
    ]


async def mark_succeeded(session: AsyncSession, job_id: UUID) -> bool:
    result = await session.execute(_SUCCEED, {"job_id": str(job_id)})
    return result.scalar_one_or_none() is not None


async def mark_failed(session: AsyncSession, job: ClaimedJob, error: str) -> JobState:
    """Requeue with backoff, or give up once `max_attempts` is spent."""
    result = await session.execute(
        _FAIL,
        {
            "job_id": str(job.id),
            "error": error[:MAX_ERROR_CHARS],
            # make_interval's `secs` is double precision.
            "backoff_seconds": float(backoff_seconds(job.attempts)),
        },
    )
    row = result.one_or_none()
    return JobState(row.state) if row else JobState.FAILED


async def heartbeat(session: AsyncSession, *, worker_id: str, job_ids: list[UUID]) -> None:
    if not job_ids:
        return
    await session.execute(
        _HEARTBEAT, {"worker_id": worker_id, "job_ids": [str(job_id) for job_id in job_ids]}
    )


async def requeue_stalled(session: AsyncSession, *, stall_seconds: int) -> list[UUID]:
    """Recover jobs whose worker died mid-flight; safe because handlers are idempotent."""
    result = await session.execute(_REQUEUE_STALLED, {"stall_seconds": float(stall_seconds)})
    return [row.id for row in result.all()]
