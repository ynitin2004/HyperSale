"""Create (idempotently) one Supabase Auth user, one workspace, and an owner membership,
then sign in and prove the API accepts the token. This is the M0 "one protected route"
acceptance, run against the hosted project with the real Supabase Auth.

Credentials for the dev user are generated once and kept in the git-ignored .env as
DEV_USER_EMAIL / DEV_USER_PASSWORD / DEV_WORKSPACE_ID so later runs reuse them.

Run from the repo root (the API need not be running unless --api is passed):
  services/backend/.venv/Scripts/python.exe scripts/seed_dev_user.py --api http://localhost:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import sys
import uuid
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DEFAULT_EMAIL = "m0-dev@hypersale.dev"
WORKSPACE_NAME = "HyperSale Dev"


def _set_env(keys: dict[str, str]) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    seen = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z0-9_]+)=", line)
        if m and m.group(1) in keys:
            lines[i] = f"{m.group(1)}={keys[m.group(1)]}"
            seen.add(m.group(1))
    extra = [k for k in keys if k not in seen]
    if extra:
        lines += ["", "# Dev user seeded by scripts/seed_dev_user.py"] + [f"{k}={keys[k]}" for k in extra]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def ensure_auth_user(client: httpx.AsyncClient, base: str, secret: str, email: str, password: str) -> str:
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    r = await client.post(
        f"{base}/auth/v1/admin/users",
        headers=headers,
        json={"email": email, "password": password, "email_confirm": True,
              "user_metadata": {"purpose": "m0-dev"}},
    )
    if r.status_code in (200, 201):
        return r.json()["id"]
    if r.status_code == 422 and "already" in r.text.lower():
        page = 1
        while True:
            lr = await client.get(f"{base}/auth/v1/admin/users", headers=headers,
                                  params={"page": page, "per_page": 200})
            lr.raise_for_status()
            users = lr.json().get("users", [])
            for u in users:
                if u.get("email") == email:
                    # Keep the stored password authoritative for later sign-ins.
                    await client.put(f"{base}/auth/v1/admin/users/{u['id']}", headers=headers,
                                     json={"password": password})
                    return u["id"]
            if len(users) < 200:
                break
            page += 1
        raise RuntimeError("user reported as existing but not found in listing")
    raise RuntimeError(f"admin user create failed: {r.status_code} {r.text[:300]}")


async def ensure_membership(admin_dsn: str, user_id: str, workspace_id: str | None) -> str:
    conn = await asyncpg.connect(admin_dsn)
    try:
        existing = await conn.fetchval(
            "SELECT workspace_id FROM memberships WHERE user_id = $1 ORDER BY created_at LIMIT 1",
            uuid.UUID(user_id),
        )
        if existing:
            return str(existing)
        ws_id = uuid.UUID(workspace_id) if workspace_id else uuid.uuid4()
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO workspaces (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                ws_id, WORKSPACE_NAME,
            )
            await conn.execute(
                "INSERT INTO memberships (id, workspace_id, user_id, role) VALUES ($1, $2, $3, 'owner')",
                uuid.uuid4(), ws_id, uuid.UUID(user_id),
            )
        return str(ws_id)
    finally:
        await conn.close()


async def sign_in(client: httpx.AsyncClient, base: str, anon_key: str, email: str, password: str) -> dict:
    r = await client.post(
        f"{base}/auth/v1/token", params={"grant_type": "password"},
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
    )
    if r.is_error:
        raise RuntimeError(f"sign-in failed: {r.status_code} {r.text[:300]}")
    return r.json()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=None, help="local API base URL to probe /api/v1/whoami")
    ap.add_argument("--token-out", default=None, help="write the access token JSON here (outside the repo)")
    args = ap.parse_args()

    env = dotenv_values(ENV_PATH)
    base = (env.get("SUPABASE_URL") or "").rstrip("/")
    secret = env.get("SUPABASE_SECRET_KEY")
    anon = env.get("SUPABASE_PUBLISHABLE_KEY")
    admin_url = env.get("ALEMBIC_DATABASE_URL") or env.get("ADMIN_DATABASE_URL")
    if not all((base, secret, anon, admin_url)):
        print("SUPABASE_URL / SUPABASE_SECRET_KEY / SUPABASE_PUBLISHABLE_KEY / ALEMBIC_DATABASE_URL required", file=sys.stderr)
        return 2
    email = env.get("DEV_USER_EMAIL") or DEFAULT_EMAIL
    password = env.get("DEV_USER_PASSWORD") or secrets.token_urlsafe(18)
    admin_dsn = make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False)

    async with httpx.AsyncClient(timeout=30) as client:
        user_id = await ensure_auth_user(client, base, secret, email, password)
        workspace_id = await ensure_membership(admin_dsn, user_id, env.get("DEV_WORKSPACE_ID"))
        _set_env({"DEV_USER_EMAIL": email, "DEV_USER_PASSWORD": password, "DEV_WORKSPACE_ID": workspace_id})
        session = await sign_in(client, base, anon, email, password)
        token = session["access_token"]
        print(f"auth user {user_id} in workspace {workspace_id}; token expires_in={session.get('expires_in')}s")
        if args.token_out:
            Path(args.token_out).write_text(json.dumps({"access_token": token, "user_id": user_id,
                                                        "workspace_id": workspace_id}), encoding="utf-8")
            print(f"token written to {args.token_out}")
        if args.api:
            r = await client.get(f"{args.api}/api/v1/whoami", headers={"Authorization": f"Bearer {token}"})
            print(f"GET /api/v1/whoami -> {r.status_code} {r.text[:200]}")
            r2 = await client.get(f"{args.api}/api/v1/whoami")
            print(f"GET /api/v1/whoami (no token) -> {r2.status_code}")
            return 0 if r.status_code == 200 and r2.status_code == 401 else 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
