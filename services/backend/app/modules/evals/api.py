"""Rater page endpoints (D37). Never returns model scores: raters label blind."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.modules.catalog import service as catalog
from app.modules.evals import service as evals
from app.modules.identity.deps import CurrentPrincipal, TenantSession

router = APIRouter()

Outcome = Literal["1", "2", "3", "4", "5", "insufficient_evidence"]


class EvalItemSummary(BaseModel):
    id: UUID
    item_key: str
    scenario_slug: str
    criteria: int
    labelled: int


class EvalTurn(BaseModel):
    idx: int
    speaker: Literal["rep", "buyer"]
    text: str


class EvalCriterion(BaseModel):
    id: str
    name: str
    description: str


class EvalItemOut(BaseModel):
    id: UUID
    item_key: str
    scenario_slug: str
    scenario_title: str | None
    turns: list[EvalTurn]
    criteria: list[EvalCriterion]
    my_labels: dict[str, Outcome]
    note: str | None


class LabelsIn(BaseModel):
    labels: dict[str, Outcome]
    note: str | None = Field(default=None, max_length=2000)


@router.get("/evals/items", response_model=list[EvalItemSummary])
async def list_items(principal: CurrentPrincipal, session: TenantSession) -> list[EvalItemSummary]:
    return [EvalItemSummary(id=p.item.id, item_key=p.item.item_key, scenario_slug=p.item.scenario_slug,
                            criteria=len(p.item.applicable_criteria), labelled=p.labelled)
            for p in await evals.list_items(session, principal)]


async def _item_out(session, principal, item_id: UUID) -> EvalItemOut:
    item, mine, note = await evals.get_item(session, principal, item_id)
    scenario = next(s for s in await catalog.list_scenarios(session) if s.slug == item.scenario_slug)
    rubric = {c.id: c for c in await catalog.get_rubric(session, scenario.rubric_version)}
    return EvalItemOut(
        id=item.id, item_key=item.item_key, scenario_slug=item.scenario_slug,
        scenario_title=scenario.title, turns=[EvalTurn(**t) for t in item.turns],
        criteria=[EvalCriterion(id=c, name=rubric[c].name, description=rubric[c].description)
                  for c in item.applicable_criteria if c in rubric],
        my_labels=mine, note=note,
    )


@router.get("/evals/items/{item_id}", response_model=EvalItemOut)
async def get_item(item_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> EvalItemOut:
    return await _item_out(session, principal, item_id)


@router.put("/evals/items/{item_id}/labels", response_model=EvalItemOut)
async def save_labels(item_id: UUID, body: LabelsIn, principal: CurrentPrincipal,
                      session: TenantSession) -> EvalItemOut:
    await evals.save_labels(session, principal, item_id, dict(body.labels), body.note)
    return await _item_out(session, principal, item_id)
