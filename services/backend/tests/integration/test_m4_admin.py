"""M4 over HTTP on real Postgres: invites and roles (D45), retention (D46), spend limit and audit (D47)."""
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.auth_admin import AccountExists
from app.adapters.storage import LocalRecordingStore
from app.config import get_settings
from app.db.session import tenant_session
from app.modules.catalog.seed import seed
from app.modules.practice import retention
from tests.integration.test_m1_loop import SECRET, _drain_jobs, stub_env  # noqa: F401
from tests.integration.test_m2_manager_evals import _member

pytestmark = pytest.mark.usefixtures("app_session_factory")


def _auth(user_id: UUID, email: str | None = None) -> dict[str, str]:
    claims = {"sub": str(user_id), "aud": "authenticated", "exp": int(time.time()) + 600}
    if email:
        claims["email"] = email
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


class FakeAuthAdmin:
    def __init__(self) -> None:
        self.created: dict[str, UUID] = {}

    async def create_user(self, email: str, password: str) -> UUID:
        if email in self.created:
            raise AccountExists(email)
        self.created[email] = uuid4()
        return self.created[email]


def _client():
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_invites_roles_and_an_append_only_audit_log(
    stub_env, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.identity import api as identity_api

    workspace_a, workspace_b, manager = two_workspaces
    owner = await _member(admin_sessionmaker, workspace_a, "owner")
    other_tenant_user = await _member(admin_sessionmaker, workspace_b, "rep")
    fake = FakeAuthAdmin()
    monkeypatch.setattr(identity_api, "build_auth_admin", lambda: fake)
    hm, ho = _auth(manager), _auth(owner)

    async with _client() as client:
        # Managers bring in reps; only an owner hands out manager.
        assert (await client.post("/api/v1/invites", json={"email": "m@x.dev", "role": "manager"},
                                  headers=hm)).status_code == 403
        assert (await client.post("/api/v1/invites", json={"email": "not-an-email", "role": "rep"},
                                  headers=hm)).status_code == 422
        created = await client.post("/api/v1/invites", json={"email": "New.Rep@X.dev", "role": "rep"}, headers=hm)
        assert created.status_code == 201, created.text
        token = created.json()["token"]
        assert created.json()["email"] == "new.rep@x.dev"

        # The join page works signed out and names the workspace.
        info = (await client.get("/api/v1/invites/lookup", params={"token": token})).json()
        assert info["workspace_name"] == "alpha" and info["role"] == "rep" and info["state"] == "pending"
        assert (await client.get("/api/v1/invites/lookup", params={"token": "x" * 43})).status_code == 404

        # New account: the API creates it, then joins it. The link works once.
        assert (await client.post("/api/v1/invites/accept", json={"token": token})).status_code == 422
        joined = await client.post("/api/v1/invites/accept", json={"token": token, "password": "long-enough-1"})
        assert joined.status_code == 200, joined.text
        new_rep = fake.created["new.rep@x.dev"]
        assert joined.json() == {"workspace_id": str(workspace_a), "role": "rep", "email": "new.rep@x.dev"}
        again = await client.post("/api/v1/invites/accept", json={"token": token, "password": "long-enough-1"})
        assert again.status_code == 410
        me = (await client.get("/api/v1/me", headers=_auth(new_rep, "new.rep@x.dev"))).json()
        assert me["role"] == "rep" and me["workspace_id"] == str(workspace_a)

        # Existing account: a forwarded link is refused; one workspace per person for now.
        token2 = (await client.post("/api/v1/invites", json={"email": "seller@x.dev", "role": "manager"},
                                    headers=ho)).json()["token"]
        assert (await client.post("/api/v1/invites/accept", json={"token": token2},
                                  headers=_auth(uuid4(), "someone.else@x.dev"))).status_code == 403
        busy = await client.post("/api/v1/invites/accept", json={"token": token2},
                                 headers=_auth(other_tenant_user, "seller@x.dev"))
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "already_in_workspace"
        seller = uuid4()
        ok = await client.post("/api/v1/invites/accept", json={"token": token2}, headers=_auth(seller, "seller@x.dev"))
        assert ok.status_code == 200 and ok.json()["role"] == "manager"

        # Revoked and expired links stop working.
        rev = (await client.post("/api/v1/invites", json={"email": "r@x.dev"}, headers=hm)).json()
        assert (await client.delete(f"/api/v1/invites/{rev['id']}", headers=hm)).status_code == 204
        assert (await client.get("/api/v1/invites/lookup", params={"token": rev["token"]})).json()["state"] == "revoked"
        assert (await client.post("/api/v1/invites/accept", json={"token": rev["token"], "password": "long-enough-1"})
                ).json()["error"]["code"] == "invite_revoked"
        exp = (await client.post("/api/v1/invites", json={"email": "e@x.dev"}, headers=hm)).json()
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(text("UPDATE invites SET expires_at = now() - interval '1 minute' WHERE id = :i"),
                            {"i": exp["id"]})
        assert (await client.post("/api/v1/invites/accept", json={"token": exp["token"], "password": "long-enough-1"})
                ).json()["error"]["code"] == "invite_expired"
        pending = (await client.get("/api/v1/invites", headers=hm)).json()
        assert [p["email"] for p in pending] == ["e@x.dev"]  # accepted and revoked drop off the list

        # Roles: owner only, and never the last owner.
        assert (await client.patch(f"/api/v1/members/{new_rep}", json={"role": "manager"}, headers=hm)).status_code == 403
        last = await client.patch(f"/api/v1/members/{owner}", json={"role": "rep"}, headers=ho)
        assert last.status_code == 409 and last.json()["error"]["code"] == "last_owner"
        assert (await client.delete(f"/api/v1/members/{owner}", headers=ho)).status_code == 409
        assert (await client.patch(f"/api/v1/members/{new_rep}", json={"role": "manager"},
                                   headers=ho)).json()["role"] == "manager"
        assert (await client.delete(f"/api/v1/members/{new_rep}", headers=ho)).status_code == 204
        assert (await client.get("/api/v1/me", headers=_auth(new_rep, "new.rep@x.dev"))).status_code == 403
        emails = {m["email"] for m in (await client.get("/api/v1/members", headers=hm)).json()}
        assert "seller@x.dev" in emails and "new.rep@x.dev" not in emails

        # The audit log is for managers and records each step.
        assert (await client.get("/api/v1/audit", headers=_auth(seller))).status_code == 200  # seller is a manager
        actions = [e["action"] for e in (await client.get("/api/v1/audit", headers=hm)).json()]
        for action in ("invite.created", "invite.accepted", "invite.revoked", "member.role_changed", "member.removed"):
            assert action in actions, action

    # Append-only at the database: the runtime role can add events, not change or remove them.
    async with tenant_session(workspace_a) as s:
        before = await s.scalar(text("SELECT count(*) FROM audit_events"))
        assert (await s.execute(text("UPDATE audit_events SET action = 'tampered'"))).rowcount == 0
        assert (await s.execute(text("DELETE FROM audit_events"))).rowcount == 0
        assert await s.scalar(text("SELECT count(*) FROM audit_events")) == before
    async with tenant_session(workspace_b) as s:
        assert await s.scalar(text("SELECT count(*) FROM invites")) == 0
        assert await s.scalar(text("SELECT count(*) FROM audit_events")) == 0


async def test_spend_limit_blocks_new_calls_and_recording_can_be_turned_off(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, _, manager = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    owner = await _member(admin_sessionmaker, workspace_a, "owner")
    ho, hm = _auth(owner), _auth(manager)
    last_month = datetime.now(UTC).replace(day=1) - timedelta(days=3)
    async with admin_sessionmaker() as s, s.begin():
        # $0.60 this month, plus $50 last month that must not count.
        await s.execute(text("INSERT INTO usage_events (workspace_id, event_type, cost_microusd) VALUES (:w, 'scoring', 600000)"),
                        {"w": str(workspace_a)})
        await s.execute(text("INSERT INTO usage_events (workspace_id, event_type, cost_microusd, created_at) "
                             "VALUES (:w, 'scoring', 50000000, :t)"), {"w": str(workspace_a), "t": last_month})

    async with _client() as client:
        scenario = (await client.get("/api/v1/catalog/scenarios", headers=hm)).json()[0]["id"]
        defaults = (await client.get("/api/v1/workspace/settings", headers=hm)).json()
        assert defaults == {"audio_retention_days": 90, "monthly_limit_microusd": 10_000_000,
                            "record_roleplay_audio": True, "month_spent_microusd": 600_000, "can_edit": False}
        settings = {"audio_retention_days": 90, "monthly_limit_microusd": 500_000, "record_roleplay_audio": True}
        assert (await client.put("/api/v1/workspace/settings", json=settings, headers=hm)).status_code == 403
        assert (await client.put("/api/v1/workspace/settings", json={**settings, "audio_retention_days": 0},
                                 headers=ho)).status_code == 422
        assert (await client.put("/api/v1/workspace/settings", json=settings, headers=ho)).status_code == 200

        blocked = await client.post("/api/v1/practice/sessions", json={"scenario_id": scenario}, headers=hm)
        assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "spend_limit_reached"
        assert "$0.60 of its $0.50" in blocked.json()["error"]["message"]
        upload = await client.post("/api/v1/reviews", json={"scenario_id": scenario, "rep_speaks_first": True,
                                                            "consent": True}, headers=hm)
        assert upload.status_code == 402

        # No limit: calls start again. Recording off: the roleplay audio is refused, uploads are not.
        await client.put("/api/v1/workspace/settings", headers=ho, json={**settings, "monthly_limit_microusd": None,
                                                                         "record_roleplay_audio": False})
        sid = (await client.post("/api/v1/practice/sessions", json={"scenario_id": scenario}, headers=hm)).json()["id"]
        chunk = await client.put(f"/api/v1/practice/sessions/{sid}/recording/0", content=b"abc",
                                 headers={**hm, "Content-Type": "audio/webm"})
        assert chunk.status_code == 409 and chunk.json()["error"]["code"] == "recording_disabled"
        rid = (await client.post("/api/v1/reviews", json={"scenario_id": scenario, "rep_speaks_first": True,
                                                          "consent": True}, headers=hm)).json()["id"]
        assert (await client.put(f"/api/v1/practice/sessions/{rid}/recording/0", content=b"abc",
                                 headers={**hm, "Content-Type": "audio/wav"})).status_code == 204

        changes = [e for e in (await client.get("/api/v1/audit", headers=hm)).json() if e["action"] == "settings.updated"]
        assert len(changes) == 2
        assert changes[0]["detail"]["record_roleplay_audio"] == {"from": True, "to": False}


async def _recorded_session(admin, workspace: UUID, user: UUID, ended_days_ago: int, store, chunks: int = 2) -> UUID:
    async with admin() as s, s.begin():
        sc = (await s.execute(text("SELECT id, persona_id FROM scenarios LIMIT 1"))).one()
        sid = (await s.execute(text(
            "INSERT INTO practice_sessions (workspace_id, user_id, scenario_id, persona_id, prompt_version, "
            "rubric_version, provider, cap_seconds, status, recording_chunks, recording_bytes, recording_mime, ended_at) "
            "VALUES (:w, :u, :sc, :p, 'v', 'rubric-v1', 'stub', 60, 'ended', :n, 6, 'audio/webm', :ended) "
            "RETURNING id"), {"w": str(workspace), "u": str(user), "sc": sc.id, "p": sc.persona_id, "n": chunks,
                              "ended": datetime.now(UTC) - timedelta(days=ended_days_ago)})).scalar_one()
    for seq in range(chunks):
        await store.put_chunk(workspace, sid, seq, b"abc")
    return sid


async def test_retention_deletes_expired_audio_from_storage_and_keeps_the_transcript(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    workspace_a, workspace_b, manager = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    store = LocalRecordingStore(get_settings().recording_dir)
    other = await _member(admin_sessionmaker, workspace_b, "rep")
    old = await _recorded_session(admin_sessionmaker, workspace_a, manager, 91, store)
    recent = await _recorded_session(admin_sessionmaker, workspace_a, manager, 10, store)
    foreign = await _recorded_session(admin_sessionmaker, workspace_b, other, 400, store)
    async with admin_sessionmaker() as s, s.begin():
        # Workspace B keeps audio forever.
        await s.execute(text("INSERT INTO workspace_settings (workspace_id, audio_retention_days) VALUES (:w, NULL)"),
                        {"w": str(workspace_b)})
        await s.execute(text("INSERT INTO transcript_turns (workspace_id, session_id, idx, speaker, text, start_ms, "
                             "end_ms, item_id) VALUES (:w, :s, 0, 'rep', 'hello', 0, 10, 'i0')"),
                        {"w": str(workspace_a), "s": str(old)})

    # The worker's daily schedule: once per workspace per UTC day, however often it ticks.
    async with admin_sessionmaker() as s, s.begin():
        assert await retention.schedule_daily(s) >= 2
    async with admin_sessionmaker() as s, s.begin():
        assert await retention.schedule_daily(s) == 0
    await _drain_jobs(admin_sessionmaker)

    assert await store.list_session(workspace_a, old) == []
    assert len(await store.list_session(workspace_a, recent)) == 2
    assert len(await store.list_session(workspace_b, foreign)) == 2
    async with _client() as client:
        hm = _auth(manager)
        gone = await client.get(f"/api/v1/practice/sessions/{old}/recording", headers=hm)
        assert gone.status_code == 410 and gone.json()["error"]["code"] == "recording_deleted"
        assert (await client.get(f"/api/v1/practice/sessions/{old}", headers=hm)).json()["recording_deleted_at"]
        assert len((await client.get(f"/api/v1/practice/sessions/{old}/transcript", headers=hm)).json()) == 1
        assert (await client.get(f"/api/v1/practice/sessions/{recent}/recording", headers=hm)).status_code == 200
        deleted = [e for e in (await client.get("/api/v1/audit", headers=hm)).json() if e["action"] == "recording.deleted"]
        assert len(deleted) == 1 and deleted[0]["target_id"] == str(old)
        assert deleted[0]["actor_user_id"] is None and deleted[0]["detail"]["objects"] == 2

    # A re-run (a retried job) finds nothing more to do.
    async with tenant_session(workspace_a) as s:
        assert await retention.sweep(s, store, workspace_a) == retention.SweepResult(0, 0)
