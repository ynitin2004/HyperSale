"""Gold set v1 (D36): versioned transcript fixtures the eval harness and raters share.

    python -m evals.goldset simulate --per-cell 2      # 5 scenarios x 3 skills x 2 seeds
    python -m evals.goldset import-live                # every live AI-rep call trace
    python -m evals.goldset list
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.catalog.seed import load_seeds
from evals.sim import SKILLS, RepProfile, simulate

GOLDSET = Path(__file__).resolve().parent / "goldset"
TRACES = Path(__file__).resolve().parents[3] / "sales-platform" / "docs" / "evidence" / "call-traces"


def load_items() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(GOLDSET.glob("*.json"))]


def _write(item: dict[str, Any]) -> Path:
    GOLDSET.mkdir(exist_ok=True)
    path = GOLDSET / f"{item['id']}.json"
    path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def cmd_simulate(per_cell: int, base_seed: int, only: str | None) -> int:
    personas, catalog = load_seeds()
    by_slug = {p.slug: p for p in personas}
    total = 0.0
    for scenario in catalog["scenarios"]:
        if only and scenario["slug"] != only:
            continue
        for skill in sorted(SKILLS):
            for k in range(per_cell):
                seed = base_seed + zlib.crc32(f"{scenario['slug']}|{skill}|{k}".encode()) % 100_000
                item_id = f"sim-{scenario['slug']}-{skill}-{seed}"
                if (GOLDSET / f"{item_id}.json").exists():
                    continue
                profile = RepProfile.draw(seed, skill)
                call = simulate(scenario, by_slug[scenario["persona"]], profile)
                total += call.spend.cost_usd
                _write({"id": item_id, "source": "sim", "scenario": scenario["slug"],
                        "applicable_criteria": scenario["applicable_criteria"],
                        "rep": asdict(profile), "turns": call.turns,
                        "created": datetime.now(UTC).date().isoformat(),
                        "spend_usd": round(call.spend.cost_usd, 4)})
                print(f"{item_id}: {len(call.turns)} turns, ${call.spend.cost_usd:.3f}", flush=True)
    print(f"simulation spend ${total:.2f}")
    return 0


def cmd_import_live() -> int:
    _, catalog = load_seeds()
    applicable = {s["slug"]: s["applicable_criteria"] for s in catalog["scenarios"]}
    n = 0
    for path in sorted(TRACES.glob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        if trace.get("rep") == "scripted" or not trace.get("transcript"):
            continue
        _write({"id": f"live-{trace['run']}", "source": "live", "scenario": trace["scenario"],
                "applicable_criteria": applicable[trace["scenario"]], "rep": trace["rep"],
                "turns": [{"idx": t["idx"], "speaker": t["speaker"], "text": t["text"]}
                          for t in trace["transcript"]],
                "created": trace["run"][:8], "session_id": trace["session_id"]})
        n += 1
    print(f"imported {n} live calls")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.goldset")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sim = sub.add_parser("simulate")
    sim.add_argument("--per-cell", type=int, default=2)
    sim.add_argument("--base-seed", type=int, default=1000)
    sim.add_argument("--scenario", default=None)
    sub.add_parser("import-live")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "simulate":
        return cmd_simulate(args.per_cell, args.base_seed, args.scenario)
    if args.cmd == "import-live":
        return cmd_import_live()
    for item in load_items():
        print(item["id"], item["source"], len(item["turns"]), "turns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
