"""Database sessions carry the tenant boundary.

Three shapes, each with a different blast radius:
  * `tenant_session`  — everything that touches workspace data; sets both tenant GUCs.
  * `identity_session` — membership lookup before a workspace is known; sets only the user GUC.
  * `system_session`   — cross-tenant plumbing (queue dispatch only); sets no GUC at all.

`SET LOCAL` cannot take bind parameters, so the GUCs go through `set_config(..., true)`,
which is transaction-local and therefore safe under Supavisor transaction pooling.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

WORKSPACE_GUC = "app.workspace_id"
USER_GUC = "app.user_id"

_SET_CONFIG = text("SELECT set_config(:name, :value, true)")


def _create_engine(url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        url or settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.database_pool_recycle_seconds,
        # Supavisor transaction pooling cannot reuse asyncpg prepared statements.
        connect_args={"statement_cache_size": 0},
    )


engine: AsyncEngine = _create_engine()
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

# The dispatch credential may bypass RLS; it is only ever used by `system_session`.
# Without WORKER_DATABASE_URL it shares the runtime engine, which is the local-dev shape.
_worker_url = get_settings().worker_database_url
worker_engine: AsyncEngine = _create_engine(_worker_url) if _worker_url else engine
WorkerSessionFactory = async_sessionmaker(worker_engine, expire_on_commit=False)


async def _set_guc(session: AsyncSession, name: str, value: str) -> None:
    await session.execute(_SET_CONFIG, {"name": name, "value": value})


@asynccontextmanager
async def tenant_session(
    workspace_id: UUID, user_id: UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """Transaction-scoped session pinned to one workspace. RLS is the second boundary."""
    async with SessionFactory() as session, session.begin():
        await _set_guc(session, WORKSPACE_GUC, str(workspace_id))
        if user_id is not None:
            await _set_guc(session, USER_GUC, str(user_id))
        yield session


@asynccontextmanager
async def identity_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """Resolve which workspaces a user belongs to, before a workspace can be pinned."""
    async with SessionFactory() as session, session.begin():
        await _set_guc(session, USER_GUC, str(user_id))
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for queue dispatch only.

    Sets no tenant GUC, so under RLS it returns nothing unless the connecting role holds
    BYPASSRLS. That role arrives via WORKER_DATABASE_URL; never point user-facing code here.
    """
    async with WorkerSessionFactory() as session, session.begin():
        yield session


async def ping() -> bool:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def dispose_engine() -> None:
    await engine.dispose()
    if worker_engine is not engine:
        await worker_engine.dispose()
