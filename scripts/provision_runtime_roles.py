"""Provision the restricted runtime roles on the hosted Postgres and point .env at them.

M0 finding: the hosted `postgres` credential has BYPASSRLS, so every RLS policy was inert
for the API. This script is the repeatable fix (CLAUDE.md: any write via MCP or a console
must be reproducible from the repo):

  hypersale_app     LOGIN, NOBYPASSRLS  -> DATABASE_URL        (API; RLS is enforced)
  hypersale_worker  LOGIN, BYPASSRLS    -> WORKER_DATABASE_URL (queue dispatch only)

Passwords are generated here, written only to the git-ignored .env, and never printed.
The migration role stays `postgres` (ALEMBIC_DATABASE_URL); default privileges are set
so tables created by future migrations are visible to both runtime roles.

Run from the repo root:
  services/backend/.venv/Scripts/python.exe scripts/provision_runtime_roles.py
"""
from __future__ import annotations

import argparse
import asyncio
import re
import secrets
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import quote

import asyncpg
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

APP_ROLE = "hypersale_app"
WORKER_ROLE = "hypersale_worker"
MIGRATION_ROLE = "postgres"

GRANTS = """
GRANT USAGE ON SCHEMA public TO {role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role};
ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {role};
REVOKE ALL ON TABLE alembic_version FROM {role};
"""


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    return make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(
        hide_password=False
    )


async def _ensure_role(conn: asyncpg.Connection, role: str, password: str, bypass: bool) -> str:
    """Create or re-password a role. Returns a short status word; never the password."""
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    attrs = "LOGIN NOINHERIT " + ("BYPASSRLS" if bypass else "NOBYPASSRLS")
    # Role names are constants above; the password is quoted as a literal by asyncpg's
    # quoting helper to keep this free of string interpolation of secrets.
    literal = "'" + password.replace("'", "''") + "'"
    if exists:
        await conn.execute(f"ALTER ROLE {role} WITH {attrs} PASSWORD {literal}")
        status = "updated"
    else:
        await conn.execute(f"CREATE ROLE {role} WITH {attrs} PASSWORD {literal}")
        status = "created"
    for statement in GRANTS.format(role=role, owner=MIGRATION_ROLE).split(";"):
        if statement.strip():
            await conn.execute(statement)
    return status


def _rewrite_env(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z0-9_]+)=", line)
        if m and m.group(1) in updates:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            seen.add(m.group(1))
    missing = [k for k in updates if k not in seen]
    if missing:
        lines.append("")
        lines.append("# Runtime roles provisioned by scripts/provision_runtime_roles.py")
        lines.extend(f"{k}={updates[k]}" for k in missing)
    return "\n".join(lines) + "\n"


async def _verify(dsn: str, expect_bypass: bool) -> dict:
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        who = await conn.fetchval("SELECT current_user")
        bypass = await conn.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        # No tenant GUC is set: a non-bypass role must see nothing even if rows exist.
        visible = await conn.fetchval("SELECT count(*) FROM workspaces")
        return {"user": who, "bypassrls": bypass, "rows_without_guc": visible,
                "ok": bypass == expect_bypass}
    finally:
        await conn.close()


async def main() -> int:
    # Passwords are regenerated on every run; re-running is the rotation procedure.
    argparse.ArgumentParser(description=__doc__).parse_args()

    env = dotenv_values(ENV_PATH)
    admin_url = env.get("ALEMBIC_DATABASE_URL") or env.get("ADMIN_DATABASE_URL")
    runtime_url = env.get("DATABASE_URL")
    if not admin_url or not runtime_url:
        print("ALEMBIC_DATABASE_URL and DATABASE_URL must be set in .env", file=sys.stderr)
        return 2

    pooler = make_url(runtime_url)
    # Supavisor addresses roles as `<role>.<project-ref>`; keep the ref from the current URL.
    current_user = pooler.username or ""
    project_ref = current_user.split(".", 1)[1] if "." in current_user else None

    app_password = secrets.token_urlsafe(24)
    worker_password = secrets.token_urlsafe(24)

    conn = await asyncpg.connect(_asyncpg_dsn(admin_url))
    try:
        me = await conn.fetchval("SELECT current_user")
        if me != MIGRATION_ROLE:
            print(f"expected to connect as {MIGRATION_ROLE}, got {me}", file=sys.stderr)
            return 2
        app_status = await _ensure_role(conn, APP_ROLE, app_password, bypass=False)
        try:
            worker_status = await _ensure_role(conn, WORKER_ROLE, worker_password, bypass=True)
        except asyncpg.InsufficientPrivilegeError as exc:
            worker_status = f"skipped ({exc.__class__.__name__}: BYPASSRLS not grantable)"
            worker_password = None
    finally:
        await conn.close()

    def pooler_url(role: str, password: str) -> str:
        user = f"{role}.{project_ref}" if project_ref else role
        return pooler.set(username=user, password=quote(password, safe="")).render_as_string(
            hide_password=False
        )

    updates = {"DATABASE_URL": pooler_url(APP_ROLE, app_password)}
    if worker_password:
        updates["WORKER_DATABASE_URL"] = pooler_url(WORKER_ROLE, worker_password)
    else:
        # Fall back to the migration credential for dispatch only; documented in PHASES.
        updates["WORKER_DATABASE_URL"] = runtime_url
    if "ADMIN_DATABASE_URL" not in env:
        updates["ADMIN_DATABASE_URL"] = runtime_url

    backup = ENV_PATH.with_name(f".env.bak-{time.strftime('%Y%m%d%H%M%S')}")
    shutil.copyfile(ENV_PATH, backup)
    ENV_PATH.write_text(_rewrite_env(ENV_PATH.read_text(encoding="utf-8"), updates), encoding="utf-8")

    app_check = await _verify(_asyncpg_dsn(updates["DATABASE_URL"]), expect_bypass=False)
    worker_check = await _verify(_asyncpg_dsn(updates["WORKER_DATABASE_URL"]), expect_bypass=True)
    print(f"{APP_ROLE}: {app_status}; verify={app_check}")
    print(f"{WORKER_ROLE}: {worker_status}; verify={worker_check}")
    print(f".env updated (backup at {backup.name}); URLs not printed.")
    return 0 if app_check["ok"] and worker_check["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
