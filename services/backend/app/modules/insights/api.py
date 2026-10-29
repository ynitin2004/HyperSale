"""Latency dashboard data (PHASES M1: "latency dashboard live").

Stage timings are written where each stage happens (connect in practice, metrics and report
in scoring); this module only aggregates them, through those modules' service functions.
"""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.identity.deps import CurrentPrincipal, TenantSession
from app.modules.practice import service as practice
from app.modules.scoring import service as scoring

router = APIRouter()

# Budgets from ARCHITECTURE §5, in ms.
STAGES = [
    ("connect_ms", "Click to connected", 5000),
    ("end_to_metrics_ms", "Call end to metrics", 1000),
    ("scoring_ms", "Model scoring time", 30000),
    ("end_to_report_ms", "Call end to full report", 30000),
]


class StageOut(BaseModel):
    key: str
    label: str
    budget_ms: int
    samples: int
    p50_ms: int | None
    p95_ms: int | None
    max_ms: int | None
    within_budget: bool | None
    recent: list[int]


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


@router.get("/metrics/latency", response_model=list[StageOut])
async def latency(principal: CurrentPrincipal, session: TenantSession) -> list[StageOut]:
    rows: list[dict[str, Any]] = (
        await practice.list_timings(session, principal.workspace_id)
        + await scoring.list_timings(session, principal.workspace_id)
    )
    out = []
    for key, label, budget in STAGES:
        values = [int(r[key]) for r in rows if isinstance(r.get(key), int | float)]
        p95 = _pct(values, 0.95)
        out.append(StageOut(
            key=key, label=label, budget_ms=budget, samples=len(values), p50_ms=_pct(values, 0.5),
            p95_ms=p95, max_ms=max(values) if values else None,
            within_budget=(p95 <= budget) if p95 is not None else None, recent=values[:20],
        ))
    return out
