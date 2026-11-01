"""Permanent demo workspace (DESIGN §6): real scored calls, so a demo never opens on an empty page.

Copies every ready report from the dev workspace into "HyperSale Demo" with fresh ids, shared out
across three sample reps so the team page has something to compare. Nothing is invented: the
transcripts, scores and verified quotes are the originals, and recordings are copied in storage.
The rep accounts are memberships only; the one login is the manager's, generated once and kept in
the git-ignored .env as DEMO_USER_EMAIL / DEMO_USER_PASSWORD. Safe to re-run.

Run from the repo root:
  services/backend/.venv/Scripts/python.exe scripts/seed_demo.py
"""
from __future__ import annotations

import asyncio
import secrets
import uuid
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
WORKSPACE_NAME = "HyperSale Demo"
SOURCE_WORKSPACE = "HyperSale Dev"
MANAGER_EMAIL = "demo-manager@hypersale.dev"
REP_EMAILS = ("alex.demo@hypersale.dev", "jordan.demo@hypersale.dev", "riya.demo@hypersale.dev")


async def _copy(conn: asyncpg.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    marks = ", ".join(f"${i + 1}" for i in range(len(cols)))
    await conn.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})",
                           [tuple(r[c] for c in cols) for r in rows])


async def _manager(client: httpx.AsyncClient, env: dict[str, str]) -> str:
    """Create the manager login once; a re-run finds it through the id kept in .env."""
    if env.get("DEMO_USER_ID"):
        return env["DEMO_USER_ID"]
    password = secrets.token_urlsafe(14)
    r = await client.post("/auth/v1/admin/users", json={
        "email": MANAGER_EMAIL, "password": password, "email_confirm": True,
        "user_metadata": {"purpose": "hypersale-demo"}})
    if r.status_code not in (200, 201):
        raise SystemExit(f"could not create {MANAGER_EMAIL}: {r.status_code} {r.text[:200]}")
    user_id = r.json()["id"]
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\nDEMO_USER_ID={user_id}\nDEMO_USER_EMAIL={MANAGER_EMAIL}\nDEMO_USER_PASSWORD={password}\n")
    return user_id


async def _copy_recording(client: httpx.AsyncClient, bucket: str, src: str, dst: str, chunks: int) -> bool:
    for seq in range(chunks):
        r = await client.post("/storage/v1/object/copy", json={
            "bucketId": bucket, "sourceKey": f"{src}/{seq:05d}.part", "destinationKey": f"{dst}/{seq:05d}.part"})
        if r.status_code != 200:
            return False
    return True


async def seed(env: dict[str, str]) -> None:
    base, secret = env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    url = env.get("ALEMBIC_DATABASE_URL") or env.get("ADMIN_DATABASE_URL") or env["DATABASE_URL"]
    conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"), statement_cache_size=0)
    try:
        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=30) as client:
            manager = await _manager(client, env)
            source = await conn.fetchval("SELECT id FROM workspaces WHERE name = $1", SOURCE_WORKSPACE)
            ws = await conn.fetchval("SELECT id FROM workspaces WHERE name = $1", WORKSPACE_NAME)
            if ws is None:
                ws = await conn.fetchval("INSERT INTO workspaces (name) VALUES ($1) RETURNING id", WORKSPACE_NAME)
            if await conn.fetchval("SELECT count(*) FROM practice_sessions WHERE workspace_id = $1", ws):
                print(f"{WORKSPACE_NAME} already seeded ({ws})")
                return

            bucket = env.get("RECORDING_BUCKET") or "recordings"
            reps = [uuid.uuid4() for _ in REP_EMAILS]
            sessions = await conn.fetch(
                "SELECT s.* FROM practice_sessions s JOIN reports r ON r.session_id = s.id "
                "WHERE s.workspace_id = $1 AND r.status = 'ready' ORDER BY s.created_at", source)
            session_rows, turn_rows, report_rows, score_rows = [], [], [], []
            recordings = 0
            for n, row in enumerate(sessions):
                new_session = uuid.uuid4()
                s = {**dict(row), "id": new_session, "workspace_id": ws, "user_id": reps[n % len(reps)]}
                if s["recording_chunks"]:
                    copied = await _copy_recording(client, bucket, f"{source}/{row['id']}", f"{ws}/{new_session}",
                                                   s["recording_chunks"])
                    recordings += copied
                    if not copied:  # calls from before the bucket existed have no stored audio
                        s.update(recording_chunks=0, recording_bytes=0, recording_mime=None)
                session_rows.append(s)
                for t in await conn.fetch("SELECT * FROM transcript_turns WHERE session_id = $1", row["id"]):
                    turn_rows.append({**dict(t), "id": uuid.uuid4(), "workspace_id": ws, "session_id": new_session})
                report = await conn.fetchrow("SELECT * FROM reports WHERE session_id = $1", row["id"])
                new_report = uuid.uuid4()
                report_rows.append({**dict(report), "id": new_report, "workspace_id": ws, "session_id": new_session})
                for c in await conn.fetch("SELECT * FROM criterion_scores WHERE report_id = $1", report["id"]):
                    score_rows.append({**dict(c), "id": uuid.uuid4(), "workspace_id": ws, "report_id": new_report})

            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO memberships (workspace_id, user_id, role, email) VALUES ($1, $2, 'owner', $3) "
                    "ON CONFLICT DO NOTHING", ws, uuid.UUID(manager), MANAGER_EMAIL)
                for user, email in zip(reps, REP_EMAILS, strict=True):
                    await conn.execute("INSERT INTO memberships (workspace_id, user_id, role, email) "
                                       "VALUES ($1, $2, 'rep', $3)", ws, user, email)
                await _copy(conn, "practice_sessions", session_rows)
                await _copy(conn, "transcript_turns", turn_rows)
                await _copy(conn, "reports", report_rows)
                await _copy(conn, "criterion_scores", score_rows)
            print(f"{WORKSPACE_NAME} ({ws}): {len(session_rows)} calls, {recordings} recordings, "
                  f"{len(score_rows)} scores, {len(reps)} sample reps")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed({k: v for k, v in dotenv_values(ENV_PATH).items() if v}))
