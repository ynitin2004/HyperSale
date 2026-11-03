"""M4 gate: tenancy on every table, read from the live schema so a new table cannot be forgotten.

Each public table is either a tenant table (has `workspace_id`, or is `workspaces`) or is on the
short list of global catalog tables. Tenant tables must have RLS enabled AND forced, and every one
of their policies must be scoped by the pinned workspace (or, for invites, the token hash, D45).
Then, as the unprivileged runtime role, an unpinned session sees no rows and a pinned one sees
only its own workspace, on every tenant table.
"""
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import identity_session, tenant_session

pytestmark = pytest.mark.usefixtures("app_session_factory")

# Global content readable by every tenant and written only by the seed script (D30).
CATALOG_TABLES = {"personas", "rubric_versions", "scenarios", "drills"}
NOT_APP_DATA = {"alembic_version"}
# Policies that are not keyed on the workspace, and why each is safe.
SCOPED_OTHERWISE = {
    ("memberships", "tenant_isolation"): "app_current_user",  # own rows before a workspace is chosen
    ("invites", "invite_by_token"): "app.invite_token_hash",  # one row, by the hash of a secret token
}


async def _tables(admin: async_sessionmaker[AsyncSession]) -> list[tuple[str, bool, bool, bool]]:
    async with admin() as s:
        rows = await s.execute(text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT 1 FROM information_schema.columns col
                           WHERE col.table_schema = 'public' AND col.table_name = c.relname
                             AND col.column_name = 'workspace_id')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 1
        """))
        return [tuple(r) for r in rows]


async def test_every_table_is_a_tenant_table_with_forced_rls_or_a_known_catalog_table(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    tables = await _tables(admin_sessionmaker)
    assert len(tables) >= 18
    async with admin_sessionmaker() as s:
        policies = (await s.execute(text(
            "SELECT tablename, policyname, coalesce(qual, '') || ' ' || coalesce(with_check, '') "
            "FROM pg_policies WHERE schemaname = 'public'"))).all()
    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, name, expr in policies:
        by_table.setdefault(table, []).append((name, expr))

    for name, rls, forced, has_workspace in tables:
        if name in NOT_APP_DATA:
            continue
        if name in CATALOG_TABLES:
            assert rls and not has_workspace, name
            continue
        assert has_workspace or name == "workspaces", f"{name}: no workspace_id and not a catalog table"
        assert rls and forced, f"{name}: RLS must be enabled and forced"
        assert by_table.get(name), f"{name}: no policy"
        for policy, expr in by_table[name]:
            needle = SCOPED_OTHERWISE.get((name, policy))
            assert "app_current_workspace()" in expr or (needle and needle in expr), f"{name}.{policy}: {expr}"


async def test_no_tenant_row_leaks_on_any_table(
    admin_sessionmaker: async_sessionmaker[AsyncSession], two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    """Data left by the rest of the suite gives most tables rows in many workspaces."""
    workspace_a, _, user = two_workspaces
    tenant = [t[0] for t in await _tables(admin_sessionmaker) if t[3]]
    for table in tenant:
        async with tenant_session(workspace_a) as s:
            leaked = await s.scalar(text(f"SELECT count(*) FROM {table} WHERE workspace_id <> :w"),
                                    {"w": str(workspace_a)})
            assert leaked == 0, table
        async with identity_session(user) as s:
            # Unpinned: nothing, except the caller's own membership rows.
            visible = await s.scalar(text(f"SELECT count(*) FROM {table}"))
            assert visible == (1 if table == "memberships" else 0), table
