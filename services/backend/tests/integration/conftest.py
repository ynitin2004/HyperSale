"""Integration fixtures against a real Postgres.

Tenant isolation cannot be proved with a fake: RLS only exists in the database, and it is
silently inert for superusers and table owners. These fixtures therefore connect as an
unprivileged role — the same shape as production — and skip loudly when no database is
configured rather than passing vacuously.

Set TEST_DATABASE_URL to a superuser asyncpg URL and run `alembic upgrade head` first.
"""
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import session as db_session

APP_ROLE = "hypersale_app_test"
APP_PASSWORD = "hypersale_app_test"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set; integration tests skipped"
)


@pytest.fixture(scope="session")
def admin_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def app_url(admin_url: str) -> str:
    return str(make_url(admin_url).set(username=APP_ROLE, password=APP_PASSWORD))


@pytest.fixture
async def admin_sessionmaker(admin_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Superuser connection: bypasses RLS, so it stands in for the BYPASSRLS worker role."""
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as connection:
        if (await connection.scalar(text("SELECT to_regclass('public.jobs')"))) is None:
            pytest.skip("Schema is missing; run `alembic upgrade head` against TEST_DATABASE_URL")
        await connection.execute(
            text(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}';
                END IF;
            END $$;
            """)
        )
        await connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"))
        await connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f"TO {APP_ROLE}"
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def app_session_factory(
    app_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession], monkeypatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Point the application's own session helpers at the unprivileged test role."""
    engine = create_async_engine(app_url, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionFactory", factory)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def two_workspaces(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID, UUID]]:
    """Two tenants and a user who belongs only to the first."""
    workspace_a, workspace_b, user_id = uuid4(), uuid4(), uuid4()
    async with admin_sessionmaker() as session, session.begin():
        for workspace_id, name in ((workspace_a, "alpha"), (workspace_b, "beta")):
            await session.execute(
                text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
                {"id": str(workspace_id), "name": name},
            )
        await session.execute(
            text(
                "INSERT INTO memberships (workspace_id, user_id, role) "
                "VALUES (:workspace_id, :user_id, 'manager')"
            ),
            {"workspace_id": str(workspace_a), "user_id": str(user_id)},
        )
    try:
        yield workspace_a, workspace_b, user_id
    finally:
        async with admin_sessionmaker() as session, session.begin():
            await session.execute(
                text("DELETE FROM workspaces WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [str(workspace_a), str(workspace_b)]},
            )
