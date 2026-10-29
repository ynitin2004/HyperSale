"""Catalog reads. Other modules call these functions; they never query catalog tables."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.modules.catalog.models import Drill, Persona, RubricVersion, Scenario


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    description: str


@dataclass(frozen=True)
class ScenarioView:
    id: UUID
    slug: str
    title: str
    brief: str
    call_type: str
    difficulty: str
    featured: bool
    applicable_criteria: list[str]
    rubric_version: str
    persona_id: UUID
    persona_slug: str
    persona_name: str
    persona_title: str
    persona_company: str


@dataclass(frozen=True)
class PersonaPrompt:
    id: UUID
    slug: str
    voice: str
    instructions: str
    prompt_version: str


def _view(s: Scenario, p: Persona) -> ScenarioView:
    return ScenarioView(
        id=s.id,
        slug=s.slug,
        title=s.title,
        brief=s.brief,
        call_type=s.call_type,
        difficulty=s.difficulty,
        featured=s.featured,
        applicable_criteria=list(s.applicable_criteria),
        rubric_version=s.rubric_version,
        persona_id=p.id,
        persona_slug=p.slug,
        persona_name=p.name,
        persona_title=p.title,
        persona_company=p.company,
    )


async def list_scenarios(session: AsyncSession) -> list[ScenarioView]:
    rows = await session.execute(
        select(Scenario, Persona)
        .join(Persona, Persona.id == Scenario.persona_id)
        .order_by(Scenario.sort_order, Scenario.slug)
    )
    return [_view(s, p) for s, p in rows.all()]


async def get_scenario(session: AsyncSession, scenario_id: UUID) -> ScenarioView:
    row = (
        await session.execute(
            select(Scenario, Persona)
            .join(Persona, Persona.id == Scenario.persona_id)
            .where(Scenario.id == scenario_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError("scenario_not_found", "Scenario not found", status_code=404)
    return _view(*row)


async def get_persona_prompt(session: AsyncSession, persona_id: UUID) -> PersonaPrompt:
    p = await session.get(Persona, persona_id)
    if p is None:
        raise AppError("persona_not_found", "Persona not found", status_code=404)
    return PersonaPrompt(
        id=p.id, slug=p.slug, voice=p.voice, instructions=p.instructions,
        prompt_version=p.prompt_version,
    )


async def get_rubric(session: AsyncSession, version: str) -> list[Criterion]:
    r = await session.get(RubricVersion, version)
    if r is None:
        raise AppError("rubric_not_found", f"Rubric {version} not found", status_code=404)
    return [Criterion(id=c["id"], name=c["name"], description=c["description"]) for c in r.criteria]


async def drills_for(session: AsyncSession, criterion_ids: list[str]) -> list[Drill]:
    if not criterion_ids:
        return []
    rows = await session.execute(select(Drill).where(Drill.criterion_id.in_(criterion_ids)))
    by_criterion: dict[str, list[Drill]] = {}
    for d in rows.scalars().all():
        by_criterion.setdefault(d.criterion_id, []).append(d)
    for drills in by_criterion.values():
        drills.sort(key=lambda d: d.id)
    # Keep the caller's priority order: weakest criterion first.
    return [d for cid in criterion_ids for d in by_criterion.get(cid, [])]
