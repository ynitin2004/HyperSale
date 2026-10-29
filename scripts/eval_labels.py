"""Evals workspace admin (D37): import the gold set, add raters, export human labels.

Run from the repo root with the admin database URL in .env (same precedence as the seed):
  services/backend/.venv/Scripts/python.exe scripts/eval_labels.py import-items
  services/backend/.venv/Scripts/python.exe scripts/eval_labels.py add-rater --email a@x.com
  services/backend/.venv/Scripts/python.exe scripts/eval_labels.py export

Raters are Supabase Auth users whose only membership is the Evals workspace, so tenancy keeps
them out of real practice data. `add-rater` prints a one-time password; share it privately.
`export` writes evals/labels/human-<n>.json (kind "human"); rater identity stays out of git.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend"))
EVALS = ROOT / "services" / "backend" / "evals"
WORKSPACE_NAME = "HyperSale Evals"


def _env() -> dict[str, str]:
    return {k: v for k, v in dotenv_values(ROOT / ".env").items() if v}


def _dsn(env: dict[str, str]) -> str:
    url = env.get("ALEMBIC_DATABASE_URL") or env.get("ADMIN_DATABASE_URL") or env.get("DATABASE_URL")
    if not url:
        raise SystemExit("set ADMIN_DATABASE_URL in .env")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _workspace(conn: asyncpg.Connection) -> str:
    row = await conn.fetchrow("SELECT id FROM workspaces WHERE name = $1", WORKSPACE_NAME)
    if row:
        return str(row["id"])
    return str(await conn.fetchval("INSERT INTO workspaces (name) VALUES ($1) RETURNING id", WORKSPACE_NAME))


async def import_items(env: dict[str, str]) -> None:
    conn = await asyncpg.connect(_dsn(env), statement_cache_size=0)
    try:
        ws = await _workspace(conn)
        n = 0
        for path in sorted((EVALS / "goldset").glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO eval_items (workspace_id, item_key, source, scenario_slug, applicable_criteria, turns) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb) ON CONFLICT (workspace_id, item_key) DO UPDATE "
                "SET turns = EXCLUDED.turns, applicable_criteria = EXCLUDED.applicable_criteria",
                ws, item["id"], item["source"], item["scenario"], json.dumps(item["applicable_criteria"]),
                json.dumps(item["turns"]))
            n += 1
        print(f"{n} gold items in workspace {WORKSPACE_NAME} ({ws})")
    finally:
        await conn.close()


async def add_rater(env: dict[str, str], email: str) -> None:
    base, secret = env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_SECRET_KEY"]
    password = secrets.token_urlsafe(14)
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{base}/auth/v1/admin/users", headers=headers, json={
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"purpose": "hypersale-rater"}})
        if r.status_code not in (200, 201):
            raise SystemExit(f"could not create {email}: {r.status_code} {r.text[:200]}")
        user_id = r.json()["id"]
    conn = await asyncpg.connect(_dsn(env), statement_cache_size=0)
    try:
        ws = await _workspace(conn)
        others = await conn.fetchval("SELECT count(*) FROM memberships WHERE user_id = $1", user_id)
        if others:
            raise SystemExit(f"{email} already belongs to a workspace; raters must be Evals-only (D37)")
        await conn.execute("INSERT INTO memberships (workspace_id, user_id, role, email) VALUES ($1, $2, 'rep', $3)",
                           ws, user_id, email)
    finally:
        await conn.close()
    print(f"rater {email} added. One-time password (share privately, not in chat logs): {password}")


async def export(env: dict[str, str]) -> None:
    conn = await asyncpg.connect(_dsn(env), statement_cache_size=0)
    try:
        ws = await _workspace(conn)
        rows = await conn.fetch(
            "SELECT l.rater_user_id, i.item_key, l.criterion_id, l.outcome FROM eval_labels l "
            "JOIN eval_items i ON i.id = l.item_id WHERE l.workspace_id = $1 ORDER BY 1, 2, 3", ws)
    finally:
        await conn.close()
    by_rater: dict[str, dict[str, dict[str, str]]] = {}
    for r in rows:
        by_rater.setdefault(str(r["rater_user_id"]), {}).setdefault(r["item_key"], {})[r["criterion_id"]] = r["outcome"]
    out = EVALS / "labels"
    out.mkdir(exist_ok=True)
    for n, (_, labels) in enumerate(sorted(by_rater.items()), start=1):
        doc = {"rater": f"human-{n}", "kind": "human", "labels": labels}
        (out / f"human-{n}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"human-{n}: {len(labels)} items")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("import-items")
    add = sub.add_parser("add-rater")
    add.add_argument("--email", required=True)
    sub.add_parser("export")
    args = ap.parse_args()
    env = _env()
    if args.cmd == "import-items":
        asyncio.run(import_items(env))
    elif args.cmd == "add-rater":
        asyncio.run(add_rater(env, args.email))
    else:
        asyncio.run(export(env))
    return 0


if __name__ == "__main__":
    sys.exit(main())
