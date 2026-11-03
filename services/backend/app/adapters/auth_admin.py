"""Account creation for invitees (D45), over the Supabase Auth admin API.

Only the invite-accept path calls this, after the invite token has been checked. It reuses the
secret key the API already holds for recording storage; the browser never sees it.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

import httpx

from app.config import Settings, get_settings
from app.errors import AppError

AUTH_TIMEOUT_SECONDS = 20.0


class AccountExists(Exception):
    """The email already has an account: the invitee must sign in instead."""


class AuthAdmin(Protocol):
    async def create_user(self, email: str, password: str) -> UUID: ...


class SupabaseAuthAdmin:
    def __init__(self, url: str, secret_key: str) -> None:
        self._base = url.rstrip("/") + "/auth/v1"
        self._headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}

    async def create_user(self, email: str, password: str) -> UUID:
        async with httpx.AsyncClient(timeout=AUTH_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{self._base}/admin/users", headers=self._headers, json={
                # The invite link reached this address, so it counts as confirmed.
                "email": email, "password": password, "email_confirm": True,
                "user_metadata": {"source": "hypersale-invite"},
            })
        if r.status_code == 422 and ("exists" in r.text or "already" in r.text.lower()):
            raise AccountExists(email)
        if r.status_code == 422:
            # Supabase's password rules (length, strength) come back as 422 too.
            try:
                body = r.json()
            except ValueError:
                body = {}
            message = body.get("msg") or body.get("message") or "Password was rejected"
            raise AppError("password_rejected", message, status_code=422)
        if r.is_error:
            raise AppError("account_create_failed", "Could not create the account", status_code=502)
        return UUID(r.json()["id"])


def build_auth_admin(settings: Settings | None = None) -> AuthAdmin:
    settings = settings or get_settings()
    if not (settings.supabase_url and settings.supabase_secret_key):
        raise AppError("accounts_not_configured", "Set SUPABASE_URL and SUPABASE_SECRET_KEY", status_code=503)
    return SupabaseAuthAdmin(settings.supabase_url, settings.supabase_secret_key)
