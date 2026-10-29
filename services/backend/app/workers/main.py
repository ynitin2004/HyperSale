"""Worker entrypoint: claim jobs, run them under their tenant, record the outcome.

Shares one Docker image with the API. The queue dispatcher is the only cross-tenant step;
handlers themselves always run inside a workspace-pinned session.
"""
import asyncio
import contextlib
import logging
import signal

from app.config import Settings, get_settings
from app.db.session import dispose_engine, system_session, tenant_session
from app.modules.platform import queue
from app.modules.platform.queue import ClaimedJob
from app.telemetry import setup_telemetry
from app.workers import handlers  # noqa: F401  (import registers handlers)
from app.workers.registry import get_handler, registered_types

log = logging.getLogger("hypersale.worker")

HEARTBEAT_INTERVAL_DIVISOR = 3


class Worker:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def _heartbeat_loop(self, job_ids: list) -> None:
        interval = max(self._settings.worker_stall_seconds / HEARTBEAT_INTERVAL_DIVISOR, 1.0)
        while True:
            await asyncio.sleep(interval)
            async with system_session() as session:
                await queue.heartbeat(
                    session, worker_id=self._settings.worker_id, job_ids=job_ids
                )

    async def _run_handler(self, job: ClaimedJob) -> None:
        handler = get_handler(job.type)
        if handler is None:
            raise LookupError(
                f"No handler registered for job type {job.type!r}; "
                f"known types: {registered_types()}"
            )
        async with tenant_session(job.workspace_id) as session:
            await handler(session, job)

    async def process(self, job: ClaimedJob) -> bool:
        """Run one job and persist its outcome. Returns True when the job succeeded."""
        try:
            await self._run_handler(job)
        except Exception as exc:  # noqa: BLE001 - the queue records every failure reason
            async with system_session() as session:
                state = await queue.mark_failed(session, job, f"{type(exc).__name__}: {exc}")
            log.warning(
                "job failed",
                extra={
                    "job_id": str(job.id),
                    "job_type": job.type,
                    "attempt": job.attempts,
                    "next_state": str(state),
                },
                exc_info=exc,
            )
            return False

        async with system_session() as session:
            await queue.mark_succeeded(session, job.id)
        log.info("job succeeded", extra={"job_id": str(job.id), "job_type": job.type})
        return True

    async def run_once(self) -> int:
        """One dispatch tick. Returns the number of jobs processed; used by tests."""
        async with system_session() as session:
            stalled = await queue.requeue_stalled(
                session, stall_seconds=self._settings.worker_stall_seconds
            )
        if stalled:
            log.warning("requeued stalled jobs", extra={"count": len(stalled)})

        async with system_session() as session:
            jobs = await queue.claim(
                session,
                worker_id=self._settings.worker_id,
                batch_size=self._settings.worker_batch_size,
            )
        if not jobs:
            return 0
        # The whole batch is leased, but it is processed one at a time. Heartbeat every
        # claimed job, or a slow first job lets a peer requeue the ones still waiting
        # behind it and run them twice.
        beat = asyncio.create_task(self._heartbeat_loop([job.id for job in jobs]))
        try:
            for job in jobs:
                await self.process(job)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        return len(jobs)

    async def run_forever(self) -> None:
        log.info(
            "worker started",
            extra={"worker_id": self._settings.worker_id, "handlers": registered_types()},
        )
        while not self._stopping.is_set():
            try:
                processed = await self.run_once()
            except Exception:  # noqa: BLE001 - a dispatch error must not kill the process
                log.exception("dispatch tick failed")
                processed = 0
            if processed == 0:
                # Idle backoff: wait for either new work time or shutdown, whichever first.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._settings.worker_poll_seconds
                    )
        log.info("worker stopped")


def _install_signal_handlers(worker: Worker) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            # Windows event loops do not support add_signal_handler.
            signal.signal(sig, lambda *_: worker.stop())


HEALTH_RESPONSE = (
    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n"
    b"Connection: close\r\n\r\nok"
)


async def _serve_health(port: int) -> asyncio.Server:
    """Minimal liveness endpoint: orchestrators (and the E2E harness) need something to
    probe, and a worker has no other port. Any request gets 200 while the loop is alive."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            await reader.read(1024)
            writer.write(HEALTH_RESPONSE)
            await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


async def run() -> None:
    setup_telemetry()
    settings = get_settings()
    worker = Worker(settings)
    _install_signal_handlers(worker)
    health = await _serve_health(settings.worker_health_port) if settings.worker_health_port else None
    try:
        await worker.run_forever()
    finally:
        if health is not None:
            health.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(run())
