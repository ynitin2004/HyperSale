"""RLS is the second tenancy boundary. These tests prove it is actually armed."""
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import identity_session, system_session, tenant_session
from app.modules.identity.service import list_memberships
from app.modules.platform.usage import EVENT_SCORING, UsageCost, record_usage

pytestmark = pytest.mark.usefixtures("app_session_factory")

COUNT_USAGE = text("SELECT count(*) FROM usage_events")


async def _seed_usage(
    admin_sessionmaker: async_sessionmaker[AsyncSession], workspace_id: UUID, count: int
) -> None:
    async with admin_sessionmaker() as session, session.begin():
        for index in range(count):
            await session.execute(
                text(
                    "INSERT INTO usage_events (workspace_id, event_type, cost_microusd) "
                    "VALUES (:workspace_id, :event_type, :cost)"
                ),
                {"workspace_id": str(workspace_id), "event_type": EVENT_SCORING, "cost": index},
            )


async def test_tenant_session_sees_only_its_own_rows(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, workspace_b, _ = two_workspaces
    await _seed_usage(admin_sessionmaker, workspace_a, 3)
    await _seed_usage(admin_sessionmaker, workspace_b, 5)

    async with tenant_session(workspace_a) as session:
        assert await session.scalar(COUNT_USAGE) == 3
    async with tenant_session(workspace_b) as session:
        assert await session.scalar(COUNT_USAGE) == 5


async def test_write_into_another_workspace_is_rejected(
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    """`USING` alone would let a pinned session plant a row in someone else's tenant."""
    workspace_a, workspace_b, _ = two_workspaces
    with pytest.raises(DBAPIError):
        async with tenant_session(workspace_a) as session:
            await record_usage(
                session,
                workspace_id=workspace_b,
                event_type=EVENT_SCORING,
                cost=UsageCost(cost_microusd=1, rate_missing=False),
            )


async def test_membership_is_readable_before_a_workspace_is_pinned(
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, user_id = two_workspaces
    async with identity_session(user_id) as session:
        memberships = await list_memberships(session, user_id)
    assert [m.workspace_id for m in memberships] == [workspace_a]


async def test_identity_session_cannot_read_other_users_memberships(
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    _, _, user_id = two_workspaces
    async with identity_session(user_id) as session:
        total = await session.scalar(text("SELECT count(*) FROM memberships"))
    assert total == 1


async def test_unpinned_session_sees_nothing_without_bypassrls(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    """The queue dispatcher must be deployed with BYPASSRLS; this is what it looks like
    when it is not, and it fails closed rather than leaking."""
    workspace_a, _, _ = two_workspaces
    await _seed_usage(admin_sessionmaker, workspace_a, 2)
    async with system_session() as session:
        assert await session.scalar(COUNT_USAGE) == 0
