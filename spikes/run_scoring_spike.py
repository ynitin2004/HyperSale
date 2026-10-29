"""M0 Spike 3 — one structured-output scoring call against the committed fixture transcript.

Proves, with one real call:
  * the model returns schema-valid rubric JSON (tool use forces the schema);
  * every evidence quote passes the two D13 code checks — it exists verbatim in the cited
    turn (existence) and that turn belongs to the rep (attribution) — counts must be 0/0;
  * `insufficient_evidence` is used for criteria the scenario does not cover (D17);
  * tokens and cost for one report are known numbers (PHASES M0 "cost truth").

The rubric here is v0 for the cold-call scenario only. The real rubric, prompt versioning
and ledger write belong to modules/scoring in M1; this file must not grow into that.

  services/backend/.venv/Scripts/python.exe spikes/run_scoring_spike.py [--model ID]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "backend"))

FIXTURE = ROOT / "services/backend/tests/fixtures/transcripts/priya_cold_call_01.json"
RUBRIC_VERSION = "cold-call-v0"
PROMPT_VERSION = "spike3-2026-10-24"

CRITERIA = {
    "opening_purpose": "Within the first two rep turns, states who they are and why they are calling.",
    "discovery_questions": "Asks the buyer specific questions about her situation instead of pitching.",
    "value_articulation": "Explains concretely what the product does for a freight-brokerage sales team.",
    "objection_handling": "Responds to an objection the buyer raises with a specific, relevant answer.",
    "next_step_ask": "Asks explicitly for a concrete next step with a reason.",
    # Deliberately out of scope for a cold open (D17): the model must say insufficient_evidence.
    "pricing_positioning": "Positions price against value and the buyer's budget authority.",
}

SCORE_TOOL = {
    "name": "submit_scores",
    "description": "Submit the rubric scores with verbatim evidence for each criterion.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["criteria"],
        "properties": {
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "outcome", "rationale", "evidence"],
                    "properties": {
                        "id": {"type": "string", "enum": list(CRITERIA)},
                        "outcome": {
                            "type": "string",
                            "enum": ["1", "2", "3", "4", "5", "insufficient_evidence"],
                        },
                        "rationale": {"type": "string", "maxLength": 400},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["turn_index", "quote"],
                                "properties": {
                                    "turn_index": {"type": "integer", "minimum": 0},
                                    "quote": {"type": "string", "minLength": 3, "maxLength": 300},
                                },
                            },
                        },
                    },
                },
            }
        },
    },
}

SYSTEM = f"""You score a sales rep's cold call against a rubric. Only the REP is scored; the buyer
is an AI persona and is never scored.

Rules:
- For each criterion return a 1-5 score ONLY when the transcript contains rep turns that bear on
  it, and cite 1-3 pieces of evidence. Every quote MUST be copied verbatim from the cited rep turn
  (same turn_index). Never quote the buyer as evidence of the rep's behaviour.
- If the call never reached the point where a criterion could be observed, return
  "insufficient_evidence" with an empty evidence list. Do not guess.
- Be strict: vague or generic statements earn 1-2.

Rubric version {RUBRIC_VERSION}. Criteria:
""" + "\n".join(f"- {cid}: {desc}" for cid, desc in CRITERIA.items())


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", text.casefold())).strip()


def verify(result: dict, turns: list[dict]) -> dict:
    """D13: existence + attribution, counted per quote. Both must be zero to pass."""
    fabricated, misattributed, checked = [], [], 0
    for crit in result["criteria"]:
        for ev in crit["evidence"]:
            checked += 1
            idx = ev["turn_index"]
            turn = turns[idx] if 0 <= idx < len(turns) else None
            if turn is None or normalize(ev["quote"]) not in normalize(turn["text"]):
                fabricated.append({"criterion": crit["id"], **ev})
                continue
            if turn["speaker"] != "rep":
                misattributed.append({"criterion": crit["id"], **ev, "speaker": turn["speaker"]})
    return {
        "quotes_checked": checked,
        "fabricated": fabricated,
        "misattributed": misattributed,
        "fabricated_rate": (len(fabricated) / checked) if checked else 0.0,
        "misattributed_rate": (len(misattributed) / checked) if checked else 0.0,
        "pass": not fabricated and not misattributed,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="override SCORING_MODEL (gateway model ID)")
    ap.add_argument("--in-usd-per-m", type=float, default=5.0)
    ap.add_argument("--out-usd-per-m", type=float, default=25.0)
    args = ap.parse_args()

    # Settings read .env relative to cwd; the spike is run from the repo root.
    env = dotenv_values(ROOT / ".env")
    import os

    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        if env.get(key) and not os.environ.get(key):
            os.environ[key] = env[key]

    from app.adapters.llm.client import build_client
    from app.adapters.llm.models import SCORING_MODEL

    model = args.model or SCORING_MODEL
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    turns = fixture["turns"]
    transcript = "\n".join(f"[{t['index']}] {t['speaker'].upper()}: {t['text']}" for t in turns)

    client = build_client()
    started = time.perf_counter()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[SCORE_TOOL],
            tool_choice={"type": "tool", "name": "submit_scores"},
            messages=[{"role": "user", "content": f"Transcript (turn index, speaker, text):\n{transcript}"}],
        )
    except Exception as exc:  # noqa: BLE001 - the spike's job is to record exactly what happened
        elapsed = round(time.perf_counter() - started, 2)
        print(f"FAILED after {elapsed}s: {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    elapsed = round(time.perf_counter() - started, 2)

    tool_use = next(b for b in response.content if b.type == "tool_use")
    result = tool_use.input
    checks = verify(result, turns)
    usage = response.usage
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cost_usd = (
        usage.input_tokens * args.in_usd_per_m + usage.output_tokens * args.out_usd_per_m
    ) / 1_000_000 + cache_read * args.in_usd_per_m * 0.1 / 1_000_000 + cache_write * args.in_usd_per_m * 1.25 / 1_000_000

    report = {
        "run": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "fixture": fixture["fixture_id"],
        "model_requested": model,
        "model_served": response.model,
        "provenance": {
            "rubric_version": RUBRIC_VERSION,
            "prompt_version": PROMPT_VERSION,
            "model_id": response.model,
            "metrics_version": "none-spike",
        },
        "latency_s": elapsed,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
        "cost_usd": round(cost_usd, 6),
        "rates_usd_per_m": {"input": args.in_usd_per_m, "output": args.out_usd_per_m},
        "checks": checks,
        "scores": result,
    }
    out_dir = ROOT / "spikes" / "runs"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"scoring-{report['run']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"model {response.model} in {elapsed}s; usage in={usage.input_tokens} out={usage.output_tokens} "
          f"cache_read={cache_read} cache_write={cache_write}; cost ${report['cost_usd']}")
    for crit in result["criteria"]:
        print(f"  {crit['id']:22} {crit['outcome']:22} evidence={len(crit['evidence'])}")
    print(f"D13 checks: fabricated={len(checks['fabricated'])} misattributed={len(checks['misattributed'])} "
          f"of {checks['quotes_checked']} quotes -> {'PASS' if checks['pass'] else 'FAIL'}")
    print(f"report: {out}")
    return 0 if checks["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
