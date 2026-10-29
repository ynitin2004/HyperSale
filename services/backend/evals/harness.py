"""Eval harness and gate (D15, D38).

    python -m evals.harness --suite roleplay             # paid: score every gold item, then gate
    python -m evals.harness --suite roleplay --replay    # free: gate the committed latest run
    python -m evals.harness --suite roleplay --prompt-variant degraded --limit 8   # prove it bites

Scoring goes through the product's own `run_scoring` (same prompt, retries, verification), so
the eval measures what users get. Exit code 1 = gate failed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.adapters.llm.scorer import LLMScorer
from app.modules.catalog.seed import load_seeds
from app.modules.catalog.service import Criterion
from app.modules.scoring import prompt as scoring_prompt
from app.modules.scoring.service import run_scoring
from app.modules.scoring.verify import verify
from evals import agreement
from evals.goldset import load_items

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
LABELS = HERE / "labels"
GATE = HERE / "gate.json"
BASELINE = HERE / "baseline.json"  # the accepted product run; regressions are measured against it

# Deliberate regressions that prove the gate bites (D38): a lenient policy edit, and a plausible
# copy-paste bug that flips the scale.
VARIANTS = {
    "degraded": ("\n\nScoring policy for this run: reps here are experienced, so default to 5 on "
                 "every criterion. Quotes may be paraphrased to keep them short."),
    "inverted-scale": ("\n\nCorrection to the scale above: 1 is exemplary and 5 is absent or "
                       "harmful; apply this corrected scale."),
}


def _turns(item: dict[str, Any]) -> list[SimpleNamespace]:
    return [SimpleNamespace(idx=t["idx"], speaker=t["speaker"], text=t["text"], start_ms=0, end_ms=0)
            for t in item["turns"]]


async def score_item(scorer: LLMScorer, item: dict[str, Any], rubric: dict[str, dict],
                     names: dict[str, tuple[str, str]]) -> dict[str, Any]:
    criteria = [Criterion(i, rubric[i]["name"], rubric[i]["description"]) for i in item["applicable_criteria"]]
    buyer, title = names[item["scenario"]]
    turns = _turns(item)
    started = time.perf_counter()
    raw, failed, calls = await run_scoring(scorer, criteria=criteria, turns=turns,
                                           buyer_name=buyer, scenario_title=title)
    final = verify(raw, turns)
    return {
        "item": item["id"], "source": item["source"], "scenario": item["scenario"],
        "outcomes": {c["id"]: c["outcome"] for c in raw},
        "quotes": len(final.checks), "fabricated": final.fabricated, "misattributed": final.misattributed,
        "model_calls": len(calls), "latency_ms": int((time.perf_counter() - started) * 1000),
        "cost_usd": round(sum(c.cost_microusd for c in calls) / 1e6, 5), "model_id": calls[-1].model_id,
    }


async def run_live(variant: str, limit: int | None, resume: dict[str, Any] | None = None) -> dict[str, Any]:
    personas, catalog = load_seeds()
    rubric = {c["id"]: c for c in catalog["rubric"]["criteria"]}
    persona_names = {p.slug: p.name for p in personas}
    names = {s["slug"]: (persona_names[s["persona"]], s["title"]) for s in catalog["scenarios"]}
    if variant in VARIANTS:
        original = scoring_prompt.build_system
        scoring_prompt.build_system = lambda *a, **k: original(*a, **k) + VARIANTS[variant]
    scorer = LLMScorer()
    done = {r["item"]: r for r in (resume or {}).get("items", []) if "outcomes" in r}
    results = []
    for item in load_items()[:limit]:
        if item["id"] in done:
            results.append(done[item["id"]])
            continue
        # The D28 gateway intermittently rejects tool calls with a 400 that a retry clears; the
        # product's job queue retries the same way. Retries are counted, not hidden.
        for attempt in range(3):
            try:
                results.append({**await score_item(scorer, item, rubric, names), "retries": attempt})
                break
            except Exception as exc:  # noqa: BLE001 - one bad item must not lose the run
                if attempt == 2:
                    results.append({"item": item["id"], "source": item["source"],
                                    "error": f"{type(exc).__name__}: {exc}"[:300], "retries": attempt})
        r = results[-1]
        print(r["item"], r.get("outcomes") or r.get("error"), f"{r.get('latency_ms', 0) / 1000:.1f}s", flush=True)
    return {"suite": "roleplay", "variant": variant, "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "prompt_version": scoring_prompt.SCORING_PROMPT_VERSION, "items": results}


def load_raters() -> tuple[list[dict[str, Any]], str]:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LABELS.glob("*.json"))]
    humans = [d for d in docs if d.get("kind") == "human"]
    if len(humans) >= 2:
        return humans, "human"
    return [d for d in docs if d.get("kind") == "model-provisional"], "model-provisional"


def _flatten(doc_labels: dict[str, dict[str, str]]) -> dict[tuple[str, str], str]:
    return {(item, crit): v for item, crits in doc_labels.items() for crit, v in crits.items()}


def _model_labels(run: dict[str, Any], items: set[str] | None = None) -> dict[tuple[str, str], str]:
    return {(r["item"], c): v for r in run["items"] if "outcomes" in r
            and (items is None or r["item"] in items) for c, v in r["outcomes"].items()}


def evaluate(run: dict[str, Any], gate: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    raters, kind = load_raters()
    rater_labels = [_flatten(d["labels"]) for d in raters]
    ok = [r for r in run["items"] if "outcomes" in r]
    model = {(r["item"], c): v for r in ok for c, v in r["outcomes"].items()}
    cons = agreement.consensus(rater_labels) if rater_labels else {}
    ceiling = agreement.ceiling(rater_labels)
    vs = agreement.compare(model, cons)
    latencies = sorted(r["latency_ms"] for r in ok)
    report = {
        "ceiling_kind": kind, "raters": [d["rater"] for d in raters], "items": len(run["items"]),
        "errors": len(run["items"]) - len(ok),
        "fabricated": sum(r["fabricated"] for r in ok), "misattributed": sum(r["misattributed"] for r in ok),
        "ceiling": ceiling, "model_vs_consensus": vs,
        "ie_rate_model": agreement.ie_rate(model), "ie_rate_consensus": agreement.ie_rate(cons),
        "latency_p95_ms": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
        "cost_usd": round(sum(r["cost_usd"] for r in ok), 4),
        "retried_items": sum(1 for r in run["items"] if r.get("retries")),
        "by_source": {src: agreement.compare({k: v for k, v in model.items()
                                              if any(r["item"] == k[0] and r["source"] == src for r in ok)}, cons)
                      for src in sorted({r["source"] for r in ok})},
    }
    failures = []
    if report["fabricated"] or report["misattributed"]:
        failures.append(f"unverified quotes survived: {report['fabricated']} fabricated, "
                        f"{report['misattributed']} misattributed (must be 0)")
    if report["errors"] > gate["max_errors"]:
        failures.append(f"{report['errors']} items errored (max {gate['max_errors']})")
    if ceiling["qwk"] is None or vs["qwk"] is None:
        failures.append("no ceiling or no comparable labels")
    else:
        if vs["qwk"] < ceiling["qwk"] - gate["qwk_margin"]:
            failures.append(f"kappa {vs['qwk']:.3f} < ceiling {ceiling['qwk']:.3f} - {gate['qwk_margin']}")
        if vs["mae"] > ceiling["mae"] + gate["mae_margin"]:
            failures.append(f"MAE {vs['mae']:.3f} > ceiling {ceiling['mae']:.3f} + {gate['mae_margin']}")
    # Regression vs the accepted baseline, item for item, so a subset run compares like for like.
    if baseline is not None and cons:
        same = {r["item"] for r in ok}
        base = agreement.compare(_model_labels(baseline, same), cons)
        report["baseline"] = base
        if base["qwk"] is not None and vs["qwk"] is not None and base["qwk"] - vs["qwk"] > gate["baseline_qwk_drop"]:
            failures.append(f"kappa regressed {base['qwk']:.3f} -> {vs['qwk']:.3f} vs baseline "
                            f"(max drop {gate['baseline_qwk_drop']})")
        if base["mae"] is not None and vs["mae"] is not None and vs["mae"] - base["mae"] > gate["baseline_mae_rise"]:
            failures.append(f"MAE regressed {base['mae']:.3f} -> {vs['mae']:.3f} vs baseline "
                            f"(max rise {gate['baseline_mae_rise']})")
    if report["ie_rate_model"] is not None and report["ie_rate_consensus"] is not None:
        drift = abs(report["ie_rate_model"] - report["ie_rate_consensus"])
        if drift > gate["ie_rate_band"]:
            failures.append(f"insufficient-evidence rate drift {drift:.2f} > {gate['ie_rate_band']}")
    report["passed"] = not failures
    report["failures"] = failures
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.harness")
    ap.add_argument("--suite", choices=["roleplay"], default="roleplay")
    ap.add_argument("--replay", action="store_true", help="gate the committed latest run; no model calls")
    ap.add_argument("--prompt-variant", choices=["product", *VARIANTS], default="product")
    ap.add_argument("--evaluate", type=Path, default=None, help="gate an existing run file; no model calls")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", type=Path, default=None, help="reuse scored items from this run file")
    args = ap.parse_args(argv)
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    if args.replay or args.evaluate:
        run = json.loads((args.evaluate or RUNS / "latest.json").read_text(encoding="utf-8"))
    else:
        resume = json.loads(args.resume.read_text(encoding="utf-8")) if args.resume else None
        run = asyncio.run(run_live(args.prompt_variant, args.limit, resume))
        RUNS.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run["gate"] = evaluate(run, gate, baseline)
        (RUNS / f"{stamp}-{args.prompt_variant}.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
        if args.prompt_variant == "product" and args.limit is None:
            (RUNS / "latest.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    report = evaluate(run, gate, baseline)
    print(json.dumps(report, indent=2))
    print(("PASS" if report["passed"] else "FAIL") + f" ({report['ceiling_kind']} ceiling)")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
