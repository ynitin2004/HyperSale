"""Provisional model raters (D36): stand-ins until the external raters label.

Two passes with different rater framings and a prompt that is *not* the product's scoring
prompt, so the provisional ceiling is not the scorer agreeing with itself verbatim. Output is
written as `evals/labels/model-<name>.json` with `kind: "model-provisional"`.

    python -m evals.model_rater --rater strict-vp --rater enablement-lead
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.adapters.llm.client import build_client
from app.adapters.llm.models import SCORING_MODEL
from app.modules.catalog.seed import load_seeds
from evals.agreement import IE
from evals.goldset import load_items

LABELS = Path(__file__).resolve().parent / "labels"
RATERS = {
    "strict-vp": ("You are a VP of Sales with 15 years of experience who reviews call recordings "
                  "for promotion decisions. You are demanding: 'adequate' means adequate."),
    "enablement-lead": ("You are a sales enablement lead who coaches SDRs and AEs every week. You "
                        "judge each skill on what the rep actually did, not on intentions."),
}


def _tool(ids: list[str]) -> dict[str, Any]:
    return {"name": "submit_labels", "description": "One label per listed criterion.",
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["labels"],
                             "properties": {"labels": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False,
                                 "required": ["criterion", "label"],
                                 "properties": {"criterion": {"type": "string", "enum": ids},
                                                "label": {"type": "string",
                                                          "enum": ["1", "2", "3", "4", "5", IE]}}}}}}}


def rate(item: dict[str, Any], rubric: dict[str, dict], persona: str, client: Any) -> dict[str, str]:
    ids = item["applicable_criteria"]
    criteria = "\n".join(f"- {i}: {rubric[i]['name']} - {rubric[i]['description']}" for i in ids)
    system = (f"{RATERS[persona]}\n\nRate only the REP (the buyer is a simulated persona). For each "
              f"criterion give 1 (absent or harmful), 2 (weak), 3 (adequate), 4 (strong) or 5 "
              f"(exemplary), or {IE} if the call never reached a point where it could be judged.\n\n"
              f"Criteria:\n{criteria}")
    transcript = "\n".join(f"[{t['idx']}] {t['speaker'].upper()}: {t['text']}" for t in item["turns"])
    resp = client.messages.create(model=SCORING_MODEL, max_tokens=3000, system=system,
                                  tools=[_tool(ids)], tool_choice={"type": "tool", "name": "submit_labels"},
                                  messages=[{"role": "user", "content": transcript}])
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    got = {x["criterion"]: x["label"] for x in (block.input or {}).get("labels", [])} if block else {}
    return {i: got[i] for i in ids if i in got}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.model_rater")
    ap.add_argument("--rater", action="append", choices=sorted(RATERS), required=True)
    args = ap.parse_args(argv)
    _, catalog = load_seeds()
    rubric = {c["id"]: c for c in catalog["rubric"]["criteria"]}
    client = build_client(model_id=SCORING_MODEL)
    LABELS.mkdir(exist_ok=True)
    for persona in args.rater:
        path = LABELS / f"model-{persona}.json"
        doc = (json.loads(path.read_text(encoding="utf-8")) if path.exists()
               else {"rater": f"model-{persona}", "kind": "model-provisional", "model_id": SCORING_MODEL,
                     "labels": {}})
        for item in load_items():
            if item["id"] in doc["labels"]:
                continue
            # The D28 gateway intermittently rejects tool calls (400); a retry goes through.
            for attempt in range(4):
                try:
                    doc["labels"][item["id"]] = rate(item, rubric, persona, client)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 3:
                        raise
                    print(f"retry {item['id']}: {type(exc).__name__}", flush=True)
                    time.sleep(3)
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            print(persona, item["id"], doc["labels"][item["id"]], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
