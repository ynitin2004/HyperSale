from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.catalog import service
from app.modules.identity.deps import CurrentPrincipal, TenantSession

router = APIRouter()


class ScenarioOut(BaseModel):
    id: UUID
    slug: str
    title: str
    brief: str
    call_type: str
    difficulty: str
    featured: bool
    applicable_criteria: list[str]
    rubric_version: str
    persona_name: str
    persona_title: str
    persona_company: str


class RubricCriterionOut(BaseModel):
    id: str
    name: str
    description: str


def _out(v: service.ScenarioView) -> ScenarioOut:
    return ScenarioOut(
        id=v.id, slug=v.slug, title=v.title, brief=v.brief, call_type=v.call_type,
        difficulty=v.difficulty, featured=v.featured,
        applicable_criteria=v.applicable_criteria, rubric_version=v.rubric_version,
        persona_name=v.persona_name, persona_title=v.persona_title,
        persona_company=v.persona_company,
    )


@router.get("/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(_principal: CurrentPrincipal, session: TenantSession) -> list[ScenarioOut]:
    return [_out(v) for v in await service.list_scenarios(session)]


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(
    scenario_id: UUID, _principal: CurrentPrincipal, session: TenantSession
) -> ScenarioOut:
    return _out(await service.get_scenario(session, scenario_id))


@router.get("/rubrics/{version}", response_model=list[RubricCriterionOut])
async def get_rubric(
    version: str, _principal: CurrentPrincipal, session: TenantSession
) -> list[RubricCriterionOut]:
    return [RubricCriterionOut(id=c.id, name=c.name, description=c.description)
            for c in await service.get_rubric(session, version)]
