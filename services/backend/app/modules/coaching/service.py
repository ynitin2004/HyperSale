"""Manager loop (D39). Reads practice, scoring and identity through their services only.

An assignment is complete when the assignee has a session for that scenario created after the
assignment whose report is ready or degraded - derived on read, so the call path is untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import fmean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.modules.catalog import service as catalog
from app.modules.coaching.models import Assignment
from app.modules.identity.service import ROLE_MANAGER, Principal, list_members
from app.modules.practice import service as practice
from app.modules.scoring import service as scoring

DONE = ("ready", "degraded")


@dataclass
class AssignmentView:
    assignment: Assignment
    completed_session_id: UUID | None
    completed_report_id: UUID | None
    overall: float | None


@dataclass
class MemberSummary:
    user_id: UUID
    email: str | None
    role: str
    attempts: int = 0
    scored: int = 0
    mean_overall: float | None = None
    last_attempt_at: str | None = None
    criteria: dict[str, float] = field(default_factory=dict)
    open_assignments: int = 0


async def create_assignment(
    session: AsyncSession, principal: Principal, *, scenario_id: UUID, assignee_user_id: UUID,
    due_at: datetime | None, note: str | None,
) -> Assignment:
    principal.require_role(ROLE_MANAGER)
    await catalog.get_scenario(session, scenario_id)  # 404 on an unknown scenario
    members = {m.user_id for m in await list_members(session, principal.workspace_id)}
    if assignee_user_id not in members:
        raise AppError("not_a_member", "The assignee is not a member of this workspace", status_code=422)
    row = Assignment(workspace_id=principal.workspace_id, scenario_id=scenario_id,
                     assignee_user_id=assignee_user_id, assigned_by=principal.user_id,
                     due_at=due_at, note=note)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def list_assignments(session: AsyncSession, principal: Principal) -> list[AssignmentView]:
    query = select(Assignment).where(Assignment.workspace_id == principal.workspace_id)
    if not principal.has_role(ROLE_MANAGER):
        query = query.where(Assignment.assignee_user_id == principal.user_id)
    rows = list((await session.execute(query.order_by(Assignment.created_at.desc()))).scalars().all())
    if not rows:
        return []
    sessions = await practice.workspace_sessions(session, principal.workspace_id)
    reports = await scoring.reports_for_sessions(session, [s.id for s in sessions])
    views = []
    for a in rows:
        # Oldest qualifying attempt after the assignment completes it.
        done = next((s for s in reversed(sessions)
                     if s.user_id == a.assignee_user_id and s.scenario_id == a.scenario_id
                     and s.created_at >= a.created_at and s.id in reports
                     and reports[s.id].status in DONE), None)
        report = reports.get(done.id) if done else None
        views.append(AssignmentView(a, done.id if done else None, report.id if report else None,
                                    float(report.overall) if report and report.overall is not None else None))
    return views


async def team_summary(session: AsyncSession, principal: Principal) -> list[MemberSummary]:
    principal.require_role(ROLE_MANAGER)
    members = await list_members(session, principal.workspace_id)
    sessions = await practice.workspace_sessions(session, principal.workspace_id)
    reports = await scoring.reports_for_sessions(session, [s.id for s in sessions])
    scored = {sid: r for sid, r in reports.items() if r.status in DONE}
    scores = await scoring.scores_for_reports(session, [r.id for r in scored.values()])
    open_by_member: dict[UUID, int] = {}
    for view in await list_assignments(session, principal):
        if view.completed_session_id is None:
            uid = view.assignment.assignee_user_id
            open_by_member[uid] = open_by_member.get(uid, 0) + 1

    out = []
    for m in members:
        mine = [s for s in sessions if s.user_id == m.user_id]
        mine_scored = [scored[s.id] for s in mine if s.id in scored]
        per_criterion: dict[str, list[int]] = {}
        for report in mine_scored:
            for c in scores.get(report.id, []):
                if c.score is not None:
                    per_criterion.setdefault(c.criterion_id, []).append(c.score)
        overalls = [float(r.overall) for r in mine_scored if r.overall is not None]
        out.append(MemberSummary(
            user_id=m.user_id, email=m.email, role=m.role, attempts=len(mine), scored=len(mine_scored),
            mean_overall=round(fmean(overalls), 2) if overalls else None,
            last_attempt_at=mine[0].created_at.isoformat() if mine else None,
            criteria={k: round(fmean(v), 2) for k, v in sorted(per_criterion.items())},
            open_assignments=open_by_member.get(m.user_id, 0),
        ))
    return out
