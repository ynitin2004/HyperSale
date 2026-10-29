"""Report creation and scoring (FLOW chain C).

Report status: pending -> scoring -> ready | degraded | failed.
  * ready     every scored criterion carries only verified evidence;
  * degraded  verification retries were exhausted for some criterion - its unverifiable
              quotes are dropped and it is flagged, never silently kept (RULES §1);
  * failed    the model could not be reached after the job's retries.
Provenance (rubric_version, prompt_version, model_id, metrics_version) is written with the
scores in one transaction and never updated afterwards (D16).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.llm.scorer import Scorer, ScorerResult, ScorerUnavailable
from app.errors import AppError
from app.modules.catalog import service as catalog
from app.modules.platform.queue import enqueue
from app.modules.platform.usage import EVENT_SCORING, UsageCost, record_usage
from app.modules.practice import service as practice
from app.modules.scoring import prompt as scoring_prompt
from app.modules.scoring.metrics import METRICS_VERSION, compute_metrics
from app.modules.scoring.models import CriterionScore, Report
from app.modules.scoring.verify import EvidenceCheck, verify

log = logging.getLogger("hypersale.scoring")

JOB_SCORE_REPORT = "scoring.score_report"
MAX_VERIFY_RETRIES = 2
# D35: one call per report. On the D28 gateway parallel calls queue (live, 5 criteria: one
# call 10.6/28.2 s vs three parallel 23.2/38.2 s) and each split call re-sends the
# transcript. Splitting stays available for rubrics larger than v1's 7 criteria.
PARALLEL_SPLIT_MIN_CRITERIA = 8
CRITERIA_PER_CALL = 2
DRILLS_PER_REPORT = 3
FINAL_REPORT_STATUSES = ("ready", "degraded", "failed")


async def create_report(
    session: AsyncSession, *, workspace_id: UUID, session_id: UUID, rubric_version: str,
    turns: list[practice.TurnView], ended_at: datetime,
) -> Report:
    """Metrics now (< 1 s budget), the model later. Scoring is enqueued in the same
    transaction, so a report row can never exist without the job that fills it."""
    started = datetime.now(UTC)
    existing = (
        await session.execute(select(Report).where(Report.session_id == session_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    metrics = compute_metrics(turns)
    report = Report(
        workspace_id=workspace_id,
        session_id=session_id,
        status="pending",
        rubric_version=rubric_version,
        metrics_version=METRICS_VERSION,
        metrics=metrics,
        drills=[],
        timings={
            "end_to_metrics_ms": int((datetime.now(UTC) - ended_at).total_seconds() * 1000),
            "metrics_compute_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        },
    )
    session.add(report)
    await session.flush()
    await enqueue(
        session,
        workspace_id=workspace_id,
        job_type=JOB_SCORE_REPORT,
        payload={"report_id": str(report.id), "session_id": str(session_id),
                 "ended_at": ended_at.isoformat()},
        idempotency_key=f"score:{report.id}",
        max_attempts=3,
    )
    return report


def _merge(base: list[dict[str, Any]], retry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {c["id"]: c for c in base}
    for c in retry:
        by_id[c["id"]] = c
    return list(by_id.values())


async def run_scoring(
    scorer: Scorer, *, criteria: list[catalog.Criterion], turns: list[practice.TurnView],
    buyer_name: str, scenario_title: str,
) -> tuple[list[dict[str, Any]], list[EvidenceCheck], list[ScorerResult]]:
    """Call the model, verify, retry failed criteria with feedback (capped). Pure of DB."""
    ids = [c.id for c in criteria]
    system = scoring_prompt.build_system(criteria, buyer_name=buyer_name, scenario_title=scenario_title)
    transcript = scoring_prompt.render_transcript(turns)
    calls: list[ScorerResult] = []

    groups = [ids]
    if len(ids) >= PARALLEL_SPLIT_MIN_CRITERIA:
        groups = [ids[i:i + CRITERIA_PER_CALL] for i in range(0, len(ids), CRITERIA_PER_CALL)]
    firsts = await asyncio.gather(*(
        scorer.score(system=system, user=transcript, tool=scoring_prompt.build_tool(g), turns=turns)
        for g in groups
    ))
    calls.extend(firsts)
    result = []
    for group, call in zip(groups, firsts, strict=True):
        result.extend(c for c in call.criteria if c.get("id") in group)
    failed = verify(result, turns).failed

    for _ in range(MAX_VERIFY_RETRIES):
        missing = [i for i in ids if i not in {c["id"] for c in result}]
        retry_ids = sorted({f.criterion_id for f in failed} | set(missing))
        if not retry_ids:
            break
        feedback = scoring_prompt.render_feedback(failed) if failed else ""
        if missing:
            feedback += f"\nYou omitted these criteria; score them: {', '.join(missing)}."
        retry = await scorer.score(system=system, user=f"{transcript}\n\n{feedback}",
                                   tool=scoring_prompt.build_tool(retry_ids), turns=turns)
        calls.append(retry)
        result = _merge(result, [c for c in retry.criteria if c.get("id") in retry_ids])
        failed = verify(result, turns).failed
    return result, failed, calls


def pick_drill_criteria(scored: list[dict[str, Any]], applicable: list[str]) -> list[str]:
    numeric = sorted(
        (c for c in scored if c["score"] is not None), key=lambda c: (c["score"], applicable.index(c["id"]))
    )
    order = [c["id"] for c in numeric] or list(applicable)
    return order[:DRILLS_PER_REPORT]


async def persist_scores(
    session: AsyncSession, report: Report, *, criteria: list[catalog.Criterion],
    raw: list[dict[str, Any]], failed: list[EvidenceCheck], turns: list[practice.TurnView],
    model_id: str, applicable: list[str], timings: dict[str, Any],
) -> Report:
    by_idx = {t.idx: t for t in turns}
    failed_keys = {(f.criterion_id, f.turn_index, f.quote) for f in failed}
    raw_by_id = {c["id"]: c for c in raw}
    rows: list[dict[str, Any]] = []
    degraded = False

    for crit in criteria:
        item = raw_by_id.get(crit.id)
        if item is None:
            degraded = True
            rows.append({"id": crit.id, "outcome": "insufficient_evidence", "score": None,
                         "rationale": "The scoring model did not return this criterion.",
                         "evidence": [], "verified": False})
            continue
        evidence = []
        for ev in item.get("evidence") or []:
            key = (crit.id, int(ev.get("turn_index", -1)), str(ev.get("quote", "")))
            if key in failed_keys:
                continue  # never persist an unverified quote
            turn = by_idx[key[1]]
            evidence.append({"turn_index": turn.idx, "quote": key[2], "speaker": turn.speaker,
                             "start_ms": turn.start_ms, "end_ms": turn.end_ms})
        outcome = str(item.get("outcome"))
        score = int(outcome) if outcome.isdigit() else None
        verified = not any(f.criterion_id == crit.id for f in failed)
        if score is not None and not evidence:
            verified = False  # a number with no surviving evidence is not trustworthy
        degraded = degraded or not verified
        rows.append({"id": crit.id, "outcome": outcome if score is None else "scored",
                     "score": score, "rationale": str(item.get("rationale", ""))[:500],
                     "evidence": evidence, "verified": verified})

    await session.execute(delete(CriterionScore).where(CriterionScore.report_id == report.id))
    for r in rows:
        session.add(CriterionScore(
            workspace_id=report.workspace_id, report_id=report.id, criterion_id=r["id"],
            outcome=r["outcome"], score=r["score"], rationale=r["rationale"],
            evidence=r["evidence"], verified=r["verified"],
        ))

    numeric = [r["score"] for r in rows if r["score"] is not None]
    drill_ids = pick_drill_criteria(rows, applicable)
    drills = await catalog.drills_for(session, drill_ids)
    chosen, seen = [], set()
    for cid in drill_ids:  # one drill per weak criterion first, then fill
        d = next((d for d in drills if d.criterion_id == cid and d.id not in seen), None)
        if d:
            chosen.append(d)
            seen.add(d.id)
    for d in drills:
        if len(chosen) >= DRILLS_PER_REPORT:
            break
        if d.id not in seen:
            chosen.append(d)
            seen.add(d.id)

    report.status = "degraded" if degraded else "ready"
    report.prompt_version = scoring_prompt.SCORING_PROMPT_VERSION
    report.model_id = model_id
    report.overall = Decimal(str(round(sum(numeric) / len(numeric), 2))) if numeric else None
    report.drills = [{"id": d.id, "criterion_id": d.criterion_id, "title": d.title,
                      "instructions": d.instructions} for d in chosen[:DRILLS_PER_REPORT]]
    report.timings = {**(report.timings or {}), **timings}
    report.completed_at = datetime.now(UTC)
    report.error = None
    await session.flush()
    return report


async def score_with_fallback(
    scorer: Scorer, fallback: Scorer | None, *, criteria: list[catalog.Criterion],
    turns: list[practice.TurnView], buyer_name: str, scenario_title: str,
) -> tuple[list[dict[str, Any]], list[EvidenceCheck], list[ScorerResult], dict[str, str] | None]:
    """D33: run the whole report on `scorer`; if it is unavailable, discard its partial
    results and run the whole report again on `fallback`. Pure of DB."""
    try:
        raw, failed, calls = await run_scoring(scorer, criteria=criteria, turns=turns,
                                               buyer_name=buyer_name, scenario_title=scenario_title)
        return raw, failed, calls, None
    except ScorerUnavailable as exc:
        if fallback is None:
            raise
        log.warning("scoring model unavailable, re-scoring on fallback",
                    extra={"model_id": exc.model_id, "fallback": fallback.model_id,
                           "reason": exc.reason[:200]})
        raw, failed, calls = await run_scoring(fallback, criteria=criteria, turns=turns,
                                               buyer_name=buyer_name, scenario_title=scenario_title)
        return raw, failed, calls, {"model_id": exc.model_id, "reason": exc.reason[:200]}


async def score_report(
    session: AsyncSession, scorer: Scorer, *, workspace_id: UUID, report_id: UUID,
    ended_at: datetime | None, fallback: Scorer | None = None,
) -> Report:
    """Idempotent: a finished report is returned untouched (stall recovery may re-deliver).

    D33: if `scorer` is unavailable the *whole* report is re-scored on `fallback`, so a
    report never mixes models and its provenance names the one that produced it."""
    report = (
        await session.execute(
            select(Report).where(Report.id == report_id, Report.workspace_id == workspace_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if report is None:
        raise LookupError(f"report {report_id} not found")
    if report.status in ("ready", "degraded"):
        return report

    sess = await practice.get_session_by_id(session, workspace_id, report.session_id)
    if sess is None:
        raise LookupError(f"session {report.session_id} not found")
    scenario = await catalog.get_scenario(session, sess.scenario_id)
    rubric = await catalog.get_rubric(session, report.rubric_version)
    criteria = [c for c in rubric if c.id in scenario.applicable_criteria]
    turns = await practice.get_transcript(session, report.session_id)
    report.attempts = (report.attempts or 0) + 1

    if not any(t.speaker == "rep" for t in turns):
        # Nothing the rep said: every criterion is honestly unobservable (D17).
        raw = [{"id": c.id, "outcome": "insufficient_evidence", "rationale":
                "No rep speech was captured in this call.", "evidence": []} for c in criteria]
        return await persist_scores(session, report, criteria=criteria, raw=raw, failed=[],
                                    turns=turns, model_id="none", applicable=scenario.applicable_criteria,
                                    timings={"scoring_ms": 0, "model_calls": 0})

    scoring_started = time.perf_counter()
    raw, failed, calls, fallback_from = await score_with_fallback(
        scorer, fallback, criteria=criteria, turns=turns, buyer_name=scenario.persona_name,
        scenario_title=scenario.title,
    )
    verification = verify(raw, turns)
    timings: dict[str, Any] = {
        "scoring_ms": int((time.perf_counter() - scoring_started) * 1000),
        "model_calls": len(calls),
        "quotes_checked": len(verification.checks),
        "quotes_rejected_final": len(failed),
    }
    if fallback_from is not None:
        timings["fallback_from"] = fallback_from
    if ended_at is not None:
        timings["end_to_report_ms"] = int((datetime.now(UTC) - ended_at).total_seconds() * 1000)

    for i, call in enumerate(calls):
        await record_usage(
            session, workspace_id=workspace_id, event_type=EVENT_SCORING, provider=call.provider,
            model_id=call.model_id, input_units=call.input_tokens, output_units=call.output_tokens,
            cost=UsageCost(cost_microusd=call.cost_microusd, rate_missing=call.rate_missing),
            metadata={"report_id": str(report_id), "call": i, "unit": "tokens",
                      "cache_read_tokens": call.cache_read_tokens},
            dedupe_key=f"scoring:{report_id}:{report.attempts}:{i}",
        )
    return await persist_scores(
        session, report, criteria=criteria, raw=raw, failed=failed, turns=turns,
        model_id=calls[-1].model_id, applicable=scenario.applicable_criteria, timings=timings,
    )


async def mark_failed(session: AsyncSession, workspace_id: UUID, report_id: UUID, error: str) -> None:
    report = (
        await session.execute(select(Report).where(Report.id == report_id, Report.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if report is not None and report.status not in ("ready", "degraded"):
        report.status = "failed"
        report.error = error[:500]
        await session.flush()


async def get_report(session: AsyncSession, workspace_id: UUID, report_id: UUID) -> tuple[Report, list[CriterionScore]]:
    report = (
        await session.execute(select(Report).where(Report.id == report_id, Report.workspace_id == workspace_id))
    ).scalar_one_or_none()
    if report is None:
        raise AppError("report_not_found", "Report not found", status_code=404)
    scores = (
        await session.execute(select(CriterionScore).where(CriterionScore.report_id == report_id))
    ).scalars().all()
    return report, list(scores)


async def report_for_session(session: AsyncSession, session_id: UUID) -> Report | None:
    return (await session.execute(select(Report).where(Report.session_id == session_id))).scalar_one_or_none()


async def reports_for_sessions(session: AsyncSession, session_ids: list[UUID]) -> dict[UUID, Report]:
    if not session_ids:
        return {}
    rows = await session.execute(select(Report).where(Report.session_id.in_(session_ids)))
    return {r.session_id: r for r in rows.scalars().all()}


async def scores_for_reports(session: AsyncSession, report_ids: list[UUID]) -> dict[UUID, list[CriterionScore]]:
    if not report_ids:
        return {}
    rows = await session.execute(select(CriterionScore).where(CriterionScore.report_id.in_(report_ids)))
    out: dict[UUID, list[CriterionScore]] = {}
    for row in rows.scalars().all():
        out.setdefault(row.report_id, []).append(row)
    return out


async def list_timings(session: AsyncSession, workspace_id: UUID, limit: int = 200) -> list[dict]:
    rows = await session.execute(
        select(Report.timings).where(Report.workspace_id == workspace_id)
        .order_by(Report.created_at.desc()).limit(limit)
    )
    return [t or {} for t in rows.scalars().all()]


async def evidence_integrity(session: AsyncSession, workspace_id: UUID) -> dict[str, int]:
    """PHASES M1 gate: zero persisted quotes may fail existence or attribution.
    Re-verifies every stored quote against the stored transcript, in code."""
    reports = (await session.execute(select(Report).where(Report.workspace_id == workspace_id))).scalars().all()
    checked = bad = 0
    for report in reports:
        turns = await practice.get_transcript(session, report.session_id)
        scores = (await session.execute(
            select(CriterionScore).where(CriterionScore.report_id == report.id))).scalars().all()
        result = verify([{"id": s.criterion_id, "evidence": s.evidence} for s in scores], turns)
        checked += len(result.checks)
        bad += len(result.failed)
    return {"reports": len(reports), "quotes_checked": checked, "quotes_failing": bad}
