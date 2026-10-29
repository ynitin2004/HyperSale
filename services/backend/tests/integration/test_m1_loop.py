"""The M1 roleplay loop end to end over HTTP, against real Postgres and stub providers (D31).

Proves in CI, with no spend: catalog -> session -> brokered (stub) call -> server-side
transcript -> end -> metrics -> scoring job -> verified report with provenance and drills ->
evidence integrity 0 -> latency samples -> recording round trip -> tenant isolation.
"""
import asyncio
import time
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.voice.stub import SCRIPT
from app.config import get_settings
from app.db.session import tenant_session
from app.modules.catalog.seed import seed
from app.modules.identity.tokens import reset_verifier
from app.modules.platform import queue
from app.workers import handlers  # noqa: F401  (import registers the job handlers)
from app.workers.registry import get_handler

pytestmark = pytest.mark.usefixtures("app_session_factory")

SECRET = "integration-test-secret-at-least-32-bytes"


def _token(user_id: UUID) -> str:
    return jwt.encode({"sub": str(user_id), "aud": "authenticated", "exp": int(time.time()) + 600},
                      SECRET, algorithm="HS256")


@pytest.fixture
def stub_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for key, value in {
        "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_JWKS_URL": "",
        "VOICE_PROVIDER": "stub", "SCORING_PROVIDER": "stub", "STUB_VOICE_TURN_GAP_SECONDS": "0.02",
        "RECORDING_STORE": "local", "RECORDING_DIR": str(tmp_path / "rec"),
    }.items():
        monkeypatch.setenv(key, value)
    # An empty issuer would make PyJWT demand iss == ""; unset means "not checked".
    monkeypatch.delenv("SUPABASE_JWT_ISSUER", raising=False)
    get_settings.cache_clear()
    reset_verifier()
    yield
    get_settings.cache_clear()
    reset_verifier()


async def _drain_jobs(admin: async_sessionmaker[AsyncSession]) -> int:
    """Claim as the BYPASSRLS stand-in, run each handler inside its tenant (like the worker)."""
    ran = 0
    while True:
        async with admin() as s, s.begin():
            jobs = await queue.claim(s, worker_id="it", batch_size=10)
        if not jobs:
            return ran
        for job in jobs:
            async with tenant_session(job.workspace_id) as s:
                await get_handler(job.type)(s, job)
            async with admin() as s, s.begin():
                await queue.mark_succeeded(s, job.id)
            ran += 1


async def test_roleplay_loop_end_to_end(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    from app.main import app

    workspace_a, workspace_b, user_a = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        h = {"Authorization": f"Bearer {_token(user_a)}"}

        scenarios = (await client.get("/api/v1/catalog/scenarios", headers=h)).json()
        assert len(scenarios) == 5 and scenarios[0]["featured"] is True
        scenario = next(s for s in scenarios if s["slug"] == "marcus-discovery")

        created = await client.post("/api/v1/practice/sessions", json={"scenario_id": scenario["id"]}, headers=h)
        assert created.status_code == 201, created.text
        sid = created.json()["id"]

        connected = await client.post(f"/api/v1/practice/sessions/{sid}/connect", json={}, headers=h)
        assert connected.status_code == 200, connected.text
        assert connected.json()["mode"] == "stub" and connected.json()["sdp_answer"] is None
        again = await client.post(f"/api/v1/practice/sessions/{sid}/connect", json={}, headers=h)
        assert again.status_code == 409  # one connect per session

        deadline = time.monotonic() + 10
        turns = []
        while time.monotonic() < deadline and len(turns) < len(SCRIPT):
            await asyncio.sleep(0.05)
            turns = (await client.get(f"/api/v1/practice/sessions/{sid}/transcript", headers=h)).json()
        assert len(turns) == len(SCRIPT)

        chunk = b"\x1aE\xdf\xa3" + bytes(range(200))
        up = await client.put(f"/api/v1/practice/sessions/{sid}/recording/0", content=chunk,
                              headers={**h, "Content-Type": "audio/webm;codecs=opus"})
        assert up.status_code == 204, up.text

        before = {t["idx"]: t for t in turns}
        rep_turn = next(t for t in turns if t["speaker"] == "rep")
        ended = await client.post(
            f"/api/v1/practice/sessions/{sid}/end",
            json={"recorder_offset_ms": 120,
                  # stub item ids are stub_item_<script index>; idx == script index here
                  "turn_starts": {f"stub_item_{rep_turn['idx']}": max(0, rep_turn["start_ms"] - 100),
                                  "stub_item_0": before[0]["start_ms"] + 5000}},
            headers=h)
        assert ended.status_code == 200, ended.text
        report_id = ended.json()["report_id"]
        assert report_id

        after = {t["idx"]: t for t in (await client.get(
            f"/api/v1/practice/sessions/{sid}/transcript", headers=h)).json()}
        assert after[rep_turn["idx"]]["start_ms"] == max(0, rep_turn["start_ms"] - 100)
        assert after[0]["start_ms"] == before[0]["start_ms"]  # a later start is refused (D32)
        assert after[rep_turn["idx"]]["text"] == rep_turn["text"]  # timing moves, text never

        pending = (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()
        assert pending["status"] == "pending" and pending["metrics"]["turns"] == len(SCRIPT)
        assert pending["timings"]["end_to_metrics_ms"] < 1000

        assert await _drain_jobs(admin_sessionmaker) >= 1
        report = (await client.get(f"/api/v1/reports/{report_id}", headers=h)).json()
        assert report["status"] == "ready", report
        assert {c["criterion_id"] for c in report["criteria"]} == set(scenario["applicable_criteria"])
        assert report["pending_criteria"] == []
        for crit in report["criteria"]:
            assert crit["verified"] is True
            assert all(e["speaker"] == "rep" for e in crit["evidence"])
        assert len(report["drills"]) == 3
        prov = report["provenance"]
        assert prov["rubric_version"] == "rubric-v1" and prov["model_id"] == "stub-scorer"
        assert prov["prompt_version"] and prov["metrics_version"] == "metrics-v1"
        assert len(prov["persona_prompt_version"]) == 12
        assert report["recording_available"] and report["recorder_offset_ms"] == 120
        assert report["metrics"]["next_step_with_date"] is True

        integrity = (await client.get("/api/v1/evidence/integrity", headers=h)).json()
        assert integrity["quotes_checked"] > 0 and integrity["quotes_failing"] == 0

        latency = {s["key"]: s for s in (await client.get("/api/v1/metrics/latency", headers=h)).json()}
        assert latency["connect_ms"]["samples"] == 1 and latency["end_to_metrics_ms"]["samples"] == 1

        audio = await client.get(f"/api/v1/practice/sessions/{sid}/recording", headers=h)
        assert audio.status_code == 200 and audio.content == chunk
        assert audio.headers["content-type"].startswith("audio/webm")

        listed = (await client.get("/api/v1/practice/sessions", headers=h)).json()
        assert listed[0]["id"] == sid and listed[0]["report_status"] == "ready"

        # Server-measured voice usage was ledgered once under the session ref (D29).
        async with tenant_session(workspace_a) as s:
            usage = (await s.execute(text(
                "SELECT count(*), max(metadata->>'source') FROM usage_events "
                "WHERE event_type = 'realtime_audio'"))).one()
        assert usage[0] == 1 and usage[1] == "server_socket"

        # Another tenant's member can neither see nor end this session.
        user_b = uuid4()
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(text("INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, 'owner')"),
                            {"w": str(workspace_b), "u": str(user_b)})
        hb = {"Authorization": f"Bearer {_token(user_b)}"}
        assert (await client.get(f"/api/v1/practice/sessions/{sid}", headers=hb)).status_code == 404
        assert (await client.get(f"/api/v1/reports/{report_id}", headers=hb)).status_code == 404
        assert (await client.post(f"/api/v1/practice/sessions/{sid}/end", json={}, headers=hb)).status_code == 404
        assert (await client.get("/api/v1/practice/sessions", headers=hb)).json() == []


async def test_new_tenant_tables_are_isolated_by_rls(
    admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    """RULES §4: tenancy proven per table, at the database, without the API in front."""
    workspace_a, workspace_b, user_a = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    async with admin_sessionmaker() as s, s.begin():
        scenario = (await s.execute(text("SELECT id, persona_id FROM scenarios LIMIT 1"))).one()
        sid = (await s.execute(text(
            "INSERT INTO practice_sessions (workspace_id, user_id, scenario_id, persona_id, prompt_version, "
            "rubric_version, provider, cap_seconds) VALUES (:w, :u, :sc, :p, 'v', 'rubric-v1', 'stub', 60) "
            "RETURNING id"), {"w": str(workspace_a), "u": str(user_a), "sc": scenario.id, "p": scenario.persona_id}
        )).scalar_one()
        await s.execute(text(
            "INSERT INTO transcript_turns (workspace_id, session_id, idx, speaker, text, start_ms, end_ms, item_id) "
            "VALUES (:w, :s, 0, 'rep', 'hello there', 0, 10, 'i0')"), {"w": str(workspace_a), "s": sid})
        rid = (await s.execute(text(
            "INSERT INTO reports (workspace_id, session_id, rubric_version, metrics_version) "
            "VALUES (:w, :s, 'rubric-v1', 'metrics-v1') RETURNING id"), {"w": str(workspace_a), "s": sid})).scalar_one()
        await s.execute(text(
            "INSERT INTO criterion_scores (workspace_id, report_id, criterion_id, outcome, rationale, verified) "
            "VALUES (:w, :r, 'opening', 'insufficient_evidence', 'r', true)"), {"w": str(workspace_a), "r": rid})

    for table in ("practice_sessions", "transcript_turns", "reports", "criterion_scores"):
        async with tenant_session(workspace_a) as s:
            assert await s.scalar(text(f"SELECT count(*) FROM {table}")) == 1, table
        async with tenant_session(workspace_b) as s:
            assert await s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table
    # Catalog is global content, readable from any tenant (D30).
    async with tenant_session(workspace_b) as s:
        assert await s.scalar(text("SELECT count(*) FROM scenarios")) == 5
