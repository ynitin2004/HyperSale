"""Worker dispatch behaviour without a database.

The point of these tests is the outcome bookkeeping: a handler that raises must never
leave a job stuck in `running`, and a handler must only ever see its own tenant.
"""
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.modules.platform import queue
from app.modules.platform.jobs import JobState
from app.modules.platform.queue import ClaimedJob
from app.workers import main as worker_main
from app.workers import registry

WORKSPACE = uuid4()
HANDLER_OK = "tests.ok"
HANDLER_BOOM = "tests.boom"

seen_workspaces: list[object] = []


@registry.register(HANDLER_OK)
async def _ok(session: object, job: ClaimedJob) -> None:
    seen_workspaces.append(session)


@registry.register(HANDLER_BOOM)
async def _boom(session: object, job: ClaimedJob) -> None:
    raise RuntimeError("handler exploded")


def make_job(job_type: str, attempts: int = 1) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        workspace_id=WORKSPACE,
        type=job_type,
        payload={},
        attempts=attempts,
        max_attempts=3,
    )


@pytest.fixture
def outcomes(monkeypatch: pytest.MonkeyPatch) -> dict:
    recorded: dict = {"succeeded": [], "failed": [], "tenant_sessions": []}

    @asynccontextmanager
    async def fake_system_session():
        yield "system-session"

    @asynccontextmanager
    async def fake_tenant_session(workspace_id, user_id=None):
        recorded["tenant_sessions"].append(workspace_id)
        yield f"tenant-session:{workspace_id}"

    async def fake_succeeded(_session, job_id):
        recorded["succeeded"].append(job_id)
        return True

    async def fake_failed(_session, job, error):
        recorded["failed"].append((job.id, error))
        return JobState.QUEUED if not job.is_final_attempt else JobState.FAILED

    monkeypatch.setattr(worker_main, "system_session", fake_system_session)
    monkeypatch.setattr(worker_main, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(queue, "mark_succeeded", fake_succeeded)
    monkeypatch.setattr(queue, "mark_failed", fake_failed)
    return recorded


async def test_successful_job_is_marked_succeeded(outcomes: dict) -> None:
    seen_workspaces.clear()
    job = make_job(HANDLER_OK)
    assert await worker_main.Worker().process(job) is True
    assert outcomes["succeeded"] == [job.id]
    assert outcomes["failed"] == []


async def test_handler_runs_inside_its_own_tenant_session(outcomes: dict) -> None:
    seen_workspaces.clear()
    job = make_job(HANDLER_OK)
    await worker_main.Worker().process(job)
    assert outcomes["tenant_sessions"] == [WORKSPACE]
    assert seen_workspaces == [f"tenant-session:{WORKSPACE}"]


async def test_raising_handler_is_recorded_not_swallowed(outcomes: dict) -> None:
    job = make_job(HANDLER_BOOM)
    assert await worker_main.Worker().process(job) is False
    assert outcomes["succeeded"] == []
    job_id, error = outcomes["failed"][0]
    assert job_id == job.id
    assert "handler exploded" in error


async def test_unknown_job_type_fails_the_job_instead_of_the_worker(outcomes: dict) -> None:
    job = make_job("tests.never-registered")
    assert await worker_main.Worker().process(job) is False
    _, error = outcomes["failed"][0]
    assert "No handler registered" in error
