from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.catalog import service as catalog
from app.modules.identity.deps import CurrentPrincipal, TenantSession
from app.modules.practice import service as practice
from app.modules.scoring import service as scoring

router = APIRouter()


class EvidenceOut(BaseModel):
    turn_index: int
    quote: str
    speaker: Literal["rep", "buyer"]
    start_ms: int
    end_ms: int


class ScoredCriterionOut(BaseModel):
    criterion_id: str
    name: str
    description: str
    outcome: str
    score: int | None
    rationale: str
    evidence: list[EvidenceOut]
    verified: bool


class DrillOut(BaseModel):
    id: str
    criterion_id: str
    title: str
    instructions: str


class ProvenanceOut(BaseModel):
    rubric_version: str
    prompt_version: str | None
    model_id: str | None
    metrics_version: str
    persona_prompt_version: str


class ReportOut(BaseModel):
    id: UUID
    session_id: UUID
    status: Literal["pending", "scoring", "ready", "degraded", "failed"]
    scenario_title: str
    persona_name: str
    metrics: dict[str, Any]
    overall: float | None
    criteria: list[ScoredCriterionOut]
    pending_criteria: list[str]
    drills: list[DrillOut]
    provenance: ProvenanceOut
    timings: dict[str, Any]
    error: str | None
    recording_available: bool
    recorder_offset_ms: int | None
    created_at: str
    completed_at: str | None


class IntegrityOut(BaseModel):
    reports: int
    quotes_checked: int
    quotes_failing: int


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> ReportOut:
    report, scores = await scoring.get_report(session, principal.workspace_id, report_id)
    # Visibility follows the session's: a rep sees their own reports, managers see all.
    sess = await practice.get_session(session, principal, report.session_id)
    scenario = await catalog.get_scenario(session, sess.scenario_id)
    rubric = {c.id: c for c in await catalog.get_rubric(session, report.rubric_version)}
    by_id = {s.criterion_id: s for s in scores}
    criteria = [
        ScoredCriterionOut(
            criterion_id=cid, name=rubric[cid].name, description=rubric[cid].description,
            outcome=by_id[cid].outcome, score=by_id[cid].score, rationale=by_id[cid].rationale,
            evidence=[EvidenceOut(**e) for e in by_id[cid].evidence], verified=by_id[cid].verified,
        )
        for cid in scenario.applicable_criteria if cid in by_id and cid in rubric
    ]
    return ReportOut(
        id=report.id, session_id=report.session_id, status=report.status,
        scenario_title=scenario.title, persona_name=scenario.persona_name,
        metrics=report.metrics or {}, overall=float(report.overall) if report.overall is not None else None,
        criteria=criteria,
        pending_criteria=[c for c in scenario.applicable_criteria if c not in by_id],
        drills=[DrillOut(**d) for d in report.drills or []],
        provenance=ProvenanceOut(
            rubric_version=report.rubric_version, prompt_version=report.prompt_version,
            model_id=report.model_id, metrics_version=report.metrics_version,
            persona_prompt_version=sess.prompt_version,
        ),
        timings=report.timings or {}, error=report.error,
        recording_available=bool(sess.recording_chunks), recorder_offset_ms=sess.recorder_offset_ms,
        created_at=report.created_at.isoformat(),
        completed_at=report.completed_at.isoformat() if report.completed_at else None,
    )


@router.get("/evidence/integrity", response_model=IntegrityOut)
async def evidence_integrity(principal: CurrentPrincipal, session: TenantSession) -> IntegrityOut:
    """M1 acceptance: re-verifies every persisted quote. `quotes_failing` must be 0."""
    return IntegrityOut(**await scoring.evidence_integrity(session, principal.workspace_id))
