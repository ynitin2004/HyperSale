"""M2 over HTTP on real Postgres: manager loop (D39) and blind rater labels (D37)."""
import asyncio
import json
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.voice.stub import SCRIPT
from app.db.session import tenant_session
from app.modules.catalog.seed import seed
from tests.integration.test_m1_loop import _drain_jobs, _token, stub_env  # noqa: F401

pytestmark = pytest.mark.usefixtures("app_session_factory")


async def _member(admin: async_sessionmaker[AsyncSession], workspace: UUID, role: str) -> UUID:
    user = uuid4()
    async with admin() as s, s.begin():
        await s.execute(text("INSERT INTO memberships (workspace_id, user_id, role) VALUES (:w, :u, :r)"),
                        {"w": str(workspace), "u": str(user), "r": role})
    return user


async def test_manager_assigns_rep_completes_team_summary_reflects_it(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    from app.main import app

    workspace_a, workspace_b, manager = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    rep = await _member(admin_sessionmaker, workspace_a, "rep")
    hm = {"Authorization": f"Bearer {_token(manager)}"}
    hr = {"Authorization": f"Bearer {_token(rep)}"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        scenario = next(s for s in (await client.get("/api/v1/catalog/scenarios", headers=hr)).json()
                        if s["slug"] == "marcus-discovery")
        body = {"scenario_id": scenario["id"], "assignee_user_id": str(rep), "note": "Run discovery"}
        assert (await client.post("/api/v1/assignments", json=body, headers=hr)).status_code == 403
        stranger = {**body, "assignee_user_id": str(uuid4())}
        assert (await client.post("/api/v1/assignments", json=stranger, headers=hm)).status_code == 422
        created = await client.post("/api/v1/assignments", json=body, headers=hm)
        assert created.status_code == 201, created.text

        mine = (await client.get("/api/v1/assignments", headers=hr)).json()
        assert len(mine) == 1 and mine[0]["completed_report_id"] is None

        # The rep does the assigned roleplay (stub providers, D31).
        sid = (await client.post("/api/v1/practice/sessions", json={"scenario_id": scenario["id"]},
                                 headers=hr)).json()["id"]
        assert (await client.post(f"/api/v1/practice/sessions/{sid}/connect", json={}, headers=hr)).status_code == 200
        deadline, turns = time.monotonic() + 10, []
        while time.monotonic() < deadline and len(turns) < len(SCRIPT):
            await asyncio.sleep(0.05)
            turns = (await client.get(f"/api/v1/practice/sessions/{sid}/transcript", headers=hr)).json()
        assert (await client.post(f"/api/v1/practice/sessions/{sid}/end", json={}, headers=hr)).status_code == 200
        assert await _drain_jobs(admin_sessionmaker) >= 1

        done = (await client.get("/api/v1/assignments", headers=hr)).json()[0]
        assert done["completed_session_id"] == sid and done["completed_report_id"] and done["overall"]

        assert (await client.get("/api/v1/team/summary", headers=hr)).status_code == 403
        team = {m["user_id"]: m for m in (await client.get("/api/v1/team/summary", headers=hm)).json()}
        assert team[str(rep)]["attempts"] == 1 and team[str(rep)]["scored"] == 1
        assert team[str(rep)]["mean_overall"] is not None and team[str(rep)]["criteria"]
        assert team[str(rep)]["open_assignments"] == 0 and team[str(manager)]["attempts"] == 0

        review = (await client.get(f"/api/v1/practice/sessions?user_id={rep}", headers=hm)).json()
        assert [r["id"] for r in review] == [sid] and review[0]["user_id"] == str(rep)
        # A rep cannot use the filter to read someone else's attempts.
        assert (await client.get(f"/api/v1/practice/sessions?user_id={manager}", headers=hr)).json()[0]["id"] == sid

    # Another tenant sees none of it.
    async with tenant_session(workspace_b) as s:
        assert await s.scalar(text("SELECT count(*) FROM assignments")) == 0


async def test_raters_label_blind_and_only_inside_the_evals_workspace(
    stub_env, admin_url: str, admin_sessionmaker: async_sessionmaker[AsyncSession],  # noqa: F811
    two_workspaces: tuple[UUID, UUID, UUID],
) -> None:
    from app.main import app

    workspace_a, evals_ws, manager_a = two_workspaces
    await seed(make_url(admin_url).set(drivername="postgresql").render_as_string(hide_password=False))
    r1 = await _member(admin_sessionmaker, evals_ws, "rep")
    r2 = await _member(admin_sessionmaker, evals_ws, "rep")
    turns = [{"idx": 0, "speaker": "buyer", "text": "Priya speaking."},
             {"idx": 1, "speaker": "rep", "text": "Hi Priya, this is Arjun from HyperSale."}]
    async with admin_sessionmaker() as s, s.begin():
        item_id = (await s.execute(text(
            "INSERT INTO eval_items (workspace_id, item_key, source, scenario_slug, applicable_criteria, turns) "
            "VALUES (:w, 'sim-x', 'sim', 'priya-cold-call', CAST(:c AS jsonb), CAST(:t AS jsonb)) RETURNING id"),
            {"w": str(evals_ws), "c": json.dumps(["opening", "discovery"]), "t": json.dumps(turns)})).scalar_one()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        h1 = {"Authorization": f"Bearer {_token(r1)}"}
        h2 = {"Authorization": f"Bearer {_token(r2)}"}
        listed = (await client.get("/api/v1/evals/items", headers=h1)).json()
        assert [(i["item_key"], i["labelled"]) for i in listed] == [("sim-x", 0)]
        item = (await client.get(f"/api/v1/evals/items/{item_id}", headers=h1)).json()
        assert [c["id"] for c in item["criteria"]] == ["opening", "discovery"]
        assert not {"score", "scores", "overall", "outcome", "evidence"} & item.keys()  # blind (D37)

        saved = await client.put(f"/api/v1/evals/items/{item_id}/labels", headers=h1,
                                 json={"labels": {"opening": "3", "discovery": "insufficient_evidence"}, "note": "short"})
        assert saved.status_code == 200 and saved.json()["my_labels"]["opening"] == "3"
        bad = await client.put(f"/api/v1/evals/items/{item_id}/labels", headers=h1,
                               json={"labels": {"positioning": "3"}})
        assert bad.status_code == 422
        # Rater 2 does not see rater 1's labels: labelling is independent.
        assert (await client.get(f"/api/v1/evals/items/{item_id}", headers=h2)).json()["my_labels"] == {}
        # A member of another workspace sees no eval items at all.
        ha = {"Authorization": f"Bearer {_token(manager_a)}"}
        assert (await client.get("/api/v1/evals/items", headers=ha)).json() == []
        assert (await client.get(f"/api/v1/evals/items/{item_id}", headers=ha)).status_code == 404

    for table, expected in (("eval_items", 1), ("eval_labels", 2)):
        async with tenant_session(evals_ws) as s:
            assert await s.scalar(text(f"SELECT count(*) FROM {table}")) == expected, table
        async with tenant_session(workspace_a) as s:
            assert await s.scalar(text(f"SELECT count(*) FROM {table}")) == 0, table
