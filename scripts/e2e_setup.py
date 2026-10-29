"""Prepare a database for the Playwright E2E run (stub providers, no spend, D31).

Migrates to head, seeds the catalog, and creates one workspace with an owner whose user id
is fixed, so the browser test can mint a matching HS256 token from E2E_JWT_SECRET.

    DATABASE_URL=postgresql+asyncpg://... python scripts/e2e_setup.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "services" / "backend"
E2E_USER_ID = "00000000-0000-4000-8000-0000000000e2"
E2E_WORKSPACE_ID = "00000000-0000-4000-8000-00000000a0e2"


def migrate(url: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "ALEMBIC_DATABASE_URL": url})


async def main() -> int:
    url = os.environ["DATABASE_URL"]
    sys.path.insert(0, str(BACKEND))
    from app.modules.catalog.seed import seed

    dsn = make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    print("catalog:", await seed(dsn))
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            # A clean slate per run: E2E assertions count this workspace's sessions.
            await conn.execute("DELETE FROM workspaces WHERE id = $1", E2E_WORKSPACE_ID)
            await conn.execute("INSERT INTO workspaces (id, name) VALUES ($1, 'E2E')", E2E_WORKSPACE_ID)
            await conn.execute(
                "INSERT INTO memberships (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                E2E_WORKSPACE_ID, E2E_USER_ID,
            )
    finally:
        await conn.close()
    print(f"e2e workspace {E2E_WORKSPACE_ID} owner {E2E_USER_ID}")
    return 0


if __name__ == "__main__":
    migrate(os.environ["DATABASE_URL"])
    sys.exit(asyncio.run(main()))
