"""Manager loop endpoints (D39): assignments and the team comparison."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.coaching import service as coaching
from app.modules.identity.deps import CurrentPrincipal, TenantSession

router = APIRouter()


class AssignmentIn(BaseModel):
    scenario_id: UUID
    assignee_user_id: UUID
    due_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


class AssignmentOut(BaseModel):
    id: UUID
    scenario_id: UUID
    assignee_user_id: UUID
    assigned_by: UUID
    due_at: str | None
    note: str | None
    created_at: str
    completed_session_id: UUID | None
    completed_report_id: UUID | None
    overall: float | None


class MemberSummaryOut(BaseModel):
    user_id: UUID
    email: str | None
    role: str
    attempts: int
    scored: int
    mean_overall: float | None
    last_attempt_at: str | None
    criteria: dict[str, float]
    open_assignments: int


def _out(v: coaching.AssignmentView) -> AssignmentOut:
    a = v.assignment
    return AssignmentOut(
        id=a.id, scenario_id=a.scenario_id, assignee_user_id=a.assignee_user_id, assigned_by=a.assigned_by,
        due_at=a.due_at.isoformat() if a.due_at else None, note=a.note, created_at=a.created_at.isoformat(),
        completed_session_id=v.completed_session_id, completed_report_id=v.completed_report_id, overall=v.overall,
    )


@router.post("/assignments", response_model=AssignmentOut, status_code=201)
async def create_assignment(body: AssignmentIn, principal: CurrentPrincipal, session: TenantSession) -> AssignmentOut:
    row = await coaching.create_assignment(
        session, principal, scenario_id=body.scenario_id, assignee_user_id=body.assignee_user_id,
        due_at=body.due_at, note=body.note,
    )
    return _out(coaching.AssignmentView(row, None, None, None))


@router.get("/assignments", response_model=list[AssignmentOut])
async def list_assignments(principal: CurrentPrincipal, session: TenantSession) -> list[AssignmentOut]:
    """Managers see every assignment in the workspace; reps see their own."""
    return [_out(v) for v in await coaching.list_assignments(session, principal)]


@router.get("/team/summary", response_model=list[MemberSummaryOut])
async def team_summary(principal: CurrentPrincipal, session: TenantSession) -> list[MemberSummaryOut]:
    return [MemberSummaryOut(**vars(m)) for m in await coaching.team_summary(session, principal)]
