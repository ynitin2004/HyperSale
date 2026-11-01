"""Recording review (M3): start an upload, send audio through the practice chunk endpoint, submit.

Progress is read from `GET /practice/sessions/{id}`, the same polling the report page uses.
"""
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.identity.deps import CurrentPrincipal, TenantSession
from app.modules.review import service as review

router = APIRouter()


class CreateReviewIn(BaseModel):
    scenario_id: UUID
    rep_speaks_first: bool
    consent: bool


class ReviewOut(BaseModel):
    id: UUID
    status: str


@router.post("/reviews", response_model=ReviewOut, status_code=201)
async def create_review(body: CreateReviewIn, principal: CurrentPrincipal, session: TenantSession) -> ReviewOut:
    row = await review.create_review(session, principal, body.scenario_id,
                                     rep_speaks_first=body.rep_speaks_first, consent=body.consent)
    return ReviewOut(id=row.id, status=row.status)


@router.post("/reviews/{session_id}/submit", response_model=ReviewOut)
async def submit(session_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> ReviewOut:
    row = await review.submit(session, principal, session_id)
    return ReviewOut(id=row.id, status=row.status)
