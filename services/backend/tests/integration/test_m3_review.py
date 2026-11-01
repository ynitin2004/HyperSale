"""M3 over HTTP on real Postgres: one pipeline for uploaded calls, and a killed job leaves no trace."""
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.transcription import StubTranscriber
from app.db.session import tenant_session
from app.modules.catalog.seed import seed
from app.modules.review import service as review
from app.modules.scoring import service as scoring
from tests.integration.test_m1_loop import _drain_jobs, _token, stub_env  # noqa: F401

pytestmark = pytest.mark.usefixtures("app_session_factory")


class CountingTranscriber(StubTranscriber):
    calls = 0

    async def transcribe(self, audio: bytes, mime: str | None):
        type(self).calls += 1
        return await super().transcribe(audio, mime)


async def _counts(admin: async_sessionmaker[AsyncSession], session_id: str) -> tuple[int, int, int]:
    async with admin() as s:
        turns = await s.scalar(text("SELECT count(*) FROM transcript_turns WHERE session_id = :s"), {"s": session_id})
        reports = await s.scalar(text("SELECT count(*) FROM reports WHERE session_id = :s"), {"s": session_id})
        usage = await s.scalar(text("SELECT count(*) FROM usage_events WHERE dedupe_key = :k"),
                               {"k": f"transcribe:{session_id}"})
    return turns, reports, usage


async def test_an_upload_runs_the_roleplay_pipeline_and_survives_a_killed_job(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.main import app

    workspace, _, owner = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    h = {"Authorization": f"Bearer {_token(owner)}"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        scenario = next(s for s in (await client.get("/api/v1/catalog/scenarios", headers=h)).json()
                        if s["slug"] == "marcus-discovery")
        body = {"scenario_id": scenario["id"], "rep_speaks_first": False, "consent": False}
        assert (await client.post("/api/v1/reviews", json=body, headers=h)).status_code == 422
        created = await client.post("/api/v1/reviews", json={**body, "consent": True}, headers=h)
        assert created.status_code == 201, created.text
        sid = created.json()["id"]

        submit = f"/api/v1/reviews/{sid}/submit"
        assert (await client.post(submit, headers=h)).status_code == 409  # nothing uploaded yet
        chunk = f"/api/v1/practice/sessions/{sid}/recording/0"
        audio = {"content": b"audio", "headers": {**h, "Content-Type": "audio/mpeg"}}
        assert (await client.put(chunk, **audio)).status_code == 204
        assert (await client.post(submit, headers=h)).json()["status"] == "transcribing"
        assert (await client.post(submit, headers=h)).status_code == 409
        assert (await client.put(chunk, **audio)).status_code == 409
        end = await client.post(f"/api/v1/practice/sessions/{sid}/end", json={"reason": "rep_ended"}, headers=h)
        assert end.status_code == 409

        # Killed after the provider answered but before the job committed.
        def killed(*_args, **_kwargs):
            raise RuntimeError("worker killed")

        monkeypatch.setattr(scoring, "create_report", killed)
        with pytest.raises(RuntimeError):
            async with tenant_session(workspace) as s:
                await review.process(s, CountingTranscriber(), workspace_id=workspace, session_id=UUID(sid))
        monkeypatch.undo()
        assert await _counts(admin_sessionmaker, sid) == (0, 0, 0)

        monkeypatch.setattr("app.workers.handlers.build_transcriber", CountingTranscriber)
        assert await _drain_jobs(admin_sessionmaker) >= 2  # transcribe, then the same scoring job
        turns, reports, usage = await _counts(admin_sessionmaker, sid)
        assert turns > 2 and reports == 1 and usage == 1

        async with tenant_session(workspace) as s:  # stall recovery re-delivers the finished job
            await review.process(s, CountingTranscriber(), workspace_id=workspace, session_id=UUID(sid))
        assert CountingTranscriber.calls == 2  # the killed attempt and the real one, no third
        assert await _counts(admin_sessionmaker, sid) == (turns, 1, 1)

        row = (await client.get(f"/api/v1/practice/sessions/{sid}", headers=h)).json()
        assert row["kind"] == "review" and row["status"] == "ended"
        report = (await client.get(f"/api/v1/reports/{row['report_id']}", headers=h)).json()
        assert report["status"] == "ready", report
        said = (await client.get(f"/api/v1/practice/sessions/{sid}/transcript", headers=h)).json()
        assert said[0]["speaker"] == "buyer" and said[1]["speaker"] == "rep"

        # An upload is not practice: it never counts as an attempt on the team page.
        team = (await client.get("/api/v1/team/summary", headers=h)).json()
        assert all(member["attempts"] == 0 for member in team)
