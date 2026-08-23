from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# Supavisor transaction pooling does not support asyncpg prepared-statement caching.
engine = create_async_engine(get_settings().database_url, connect_args={"statement_cache_size": 0})
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def workspace_session(workspace_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a transaction-scoped tenant session; SET LOCAL is safe with transaction pooling."""
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.workspace_id = :workspace_id"), {"workspace_id": str(workspace_id)})
            yield session

