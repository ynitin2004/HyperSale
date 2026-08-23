"""Job handler registry.

Handlers receive a workspace-pinned session, so a handler physically cannot reach another
tenant's rows. Handlers must be idempotent: stall recovery and retries can re-deliver a job.
"""
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.queue import ClaimedJob

JobHandler = Callable[[AsyncSession, ClaimedJob], Awaitable[None]]

_handlers: dict[str, JobHandler] = {}


def register(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(handler: JobHandler) -> JobHandler:
        if job_type in _handlers:
            raise ValueError(f"A handler for {job_type!r} is already registered")
        _handlers[job_type] = handler
        return handler

    return decorator


def get_handler(job_type: str) -> JobHandler | None:
    return _handlers.get(job_type)


def registered_types() -> list[str]:
    return sorted(_handlers)


def clear() -> None:
    """Test seam only."""
    _handlers.clear()
