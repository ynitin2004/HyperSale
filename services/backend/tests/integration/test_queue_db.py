"""Queue semantics that only the database can prove: SKIP LOCKED, idempotency, recovery."""
import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.platform import queue
from app.modules.platform.jobs import JobState

JOB_TYPE = "tests.integration"


async def _enqueue_many(
    sessionmaker: async_sessionmaker[AsyncSession], workspace_id: UUID, count: int
) -> None:
    async with sessionmaker() as session, session.begin():
        for index in range(count):
            await queue.enqueue(
                session,
                workspace_id=workspace_id,
                job_type=JOB_TYPE,
                payload={"index": index},
                idempotency_key=f"job-{index}",
            )


async def _state_of(sessionmaker: async_sessionmaker[AsyncSession], job_id: UUID) -> str:
    async with sessionmaker() as session:
        return await session.scalar(text("SELECT state FROM jobs WHERE id = :id"), {"id": str(job_id)})


async def test_enqueue_is_idempotent(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    async with admin_sessionmaker() as session, session.begin():
        first = await queue.enqueue(
            session,
            workspace_id=workspace_a,
            job_type=JOB_TYPE,
            payload={"n": 1},
            idempotency_key="only-once",
        )
        second = await queue.enqueue(
            session,
            workspace_id=workspace_a,
            job_type=JOB_TYPE,
            payload={"n": 2},
            idempotency_key="only-once",
        )
    assert first.created is True
    assert second.created is False
    assert first.job_id == second.job_id


async def test_claim_marks_running_and_is_not_redelivered(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 1)

    async with admin_sessionmaker() as session, session.begin():
        claimed = await queue.claim(session, worker_id="worker-1", batch_size=5)
    assert len(claimed) == 1
    assert claimed[0].payload == {"index": 0}
    assert claimed[0].attempts == 1
    assert await _state_of(admin_sessionmaker, claimed[0].id) == JobState.RUNNING

    async with admin_sessionmaker() as session, session.begin():
        assert await queue.claim(session, worker_id="worker-2", batch_size=5) == []


async def test_concurrent_workers_never_receive_the_same_job(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    """SKIP LOCKED is the whole reason this queue needs no broker."""
    workspace_a, _, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 6)

    async def claim_as(worker_id: str) -> list[UUID]:
        async with admin_sessionmaker() as session, session.begin():
            return [job.id for job in await queue.claim(session, worker_id=worker_id, batch_size=3)]

    first, second = await asyncio.gather(claim_as("worker-1"), claim_as("worker-2"))
    assert len(first) == 3
    assert len(second) == 3
    assert set(first).isdisjoint(second)


async def test_failure_requeues_with_backoff_then_gives_up(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    async with admin_sessionmaker() as session, session.begin():
        await queue.enqueue(
            session,
            workspace_id=workspace_a,
            job_type=JOB_TYPE,
            idempotency_key="fails",
            max_attempts=2,
        )

    async with admin_sessionmaker() as session, session.begin():
        job = (await queue.claim(session, worker_id="worker-1", batch_size=1))[0]
    async with admin_sessionmaker() as session, session.begin():
        assert await queue.mark_failed(session, job, "boom") == JobState.QUEUED

    async with admin_sessionmaker() as session:
        run_after = await session.scalar(
            text("SELECT run_after > now() FROM jobs WHERE id = :id"), {"id": str(job.id)}
        )
    assert run_after is True

    # Second and final attempt: the job stops retrying instead of looping forever.
    async with admin_sessionmaker() as session, session.begin():
        await session.execute(
            text("UPDATE jobs SET run_after = now() WHERE id = :id"), {"id": str(job.id)}
        )
    async with admin_sessionmaker() as session, session.begin():
        retried = (await queue.claim(session, worker_id="worker-1", batch_size=1))[0]
    assert retried.attempts == 2
    async with admin_sessionmaker() as session, session.begin():
        assert await queue.mark_failed(session, retried, "boom again") == JobState.FAILED


async def test_succeeded_job_is_terminal(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 1)
    async with admin_sessionmaker() as session, session.begin():
        job = (await queue.claim(session, worker_id="worker-1", batch_size=1))[0]
    async with admin_sessionmaker() as session, session.begin():
        assert await queue.mark_succeeded(session, job.id) is True
    # A late duplicate completion must not revive or rewrite the row.
    async with admin_sessionmaker() as session, session.begin():
        assert await queue.mark_succeeded(session, job.id) is False
    assert await _state_of(admin_sessionmaker, job.id) == JobState.SUCCEEDED


async def test_stalled_jobs_return_to_the_queue(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 1)
    async with admin_sessionmaker() as session, session.begin():
        job = (await queue.claim(session, worker_id="dead-worker", batch_size=1))[0]

    async with admin_sessionmaker() as session, session.begin():
        await session.execute(
            text("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": str(job.id)},
        )
    async with admin_sessionmaker() as session, session.begin():
        requeued = await queue.requeue_stalled(session, stall_seconds=120)
    assert requeued == [job.id]
    assert await _state_of(admin_sessionmaker, job.id) == JobState.QUEUED


async def test_heartbeat_only_refreshes_the_owning_worker(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 1)
    async with admin_sessionmaker() as session, session.begin():
        job = (await queue.claim(session, worker_id="worker-1", batch_size=1))[0]
        await session.execute(
            text("UPDATE jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": str(job.id)},
        )

    async with admin_sessionmaker() as session, session.begin():
        await queue.heartbeat(session, worker_id="worker-2", job_ids=[job.id])
    async with admin_sessionmaker() as session:
        stale = await session.scalar(
            text("SELECT heartbeat_at < now() - interval '30 minutes' FROM jobs WHERE id = :id"),
            {"id": str(job.id)},
        )
    assert stale is True, "a foreign worker must not be able to extend someone else's lease"


@pytest.mark.usefixtures("app_session_factory")
async def test_jobs_are_invisible_across_tenants(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    from app.db.session import tenant_session

    workspace_a, workspace_b, _ = two_workspaces
    await _enqueue_many(admin_sessionmaker, workspace_a, 2)
    async with tenant_session(workspace_b) as session:
        assert await session.scalar(text("SELECT count(*) FROM jobs")) == 0
