"""Push a voice-spike run's measured usage through the real metering path.

M0 Spike 1 is only closed when a real session's token usage reaches `usage_events` via
API -> queue -> worker, not by inserting a row by hand. This reads a run's report.json
from spikes/run_voice_spike.py and POSTs it as the browser would.

  services/backend/.venv/Scripts/python.exe scripts/report_spike_usage.py \
      --run spikes/runs/<run-dir> --token "$TEMP/hypersale_dev_token.json" --api http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--token", required=True, help="JSON file from seed_dev_user.py --token-out")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    report = json.loads(Path(args.run, "report.json").read_text(encoding="utf-8"))
    token = json.loads(Path(args.token).read_text(encoding="utf-8"))["access_token"]
    usage = report["cost_truth"]["usage_tokens"]
    seconds = report["cost_truth"]["session_seconds"] or 0

    body = {
        "session_ref": f"spike-{report['run']}-{report['browser']}",
        "provider": "azure",
        "model_id": report["model"],
        # The spike has no per-direction timing; the session length is attributed to both
        # sides so the descriptive seconds stay honest without inventing a split.
        "input_seconds": seconds,
        "output_seconds": seconds,
        "tokens": {k: usage[k] for k in (
            "text_in", "text_in_cached", "audio_in", "audio_in_cached", "text_out", "audio_out"
        )},
    }
    r = httpx.post(
        f"{args.api}/api/v1/practice/realtime/usage",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print(f"POST /api/v1/practice/realtime/usage -> {r.status_code} {r.text[:300]}")
    if r.is_error:
        return 1
    print(f"spike-computed cost: ${report['cost_truth']['cost']['total_usd']} "
          f"({report['cost_truth']['cost']['total_microusd']} microusd); the worker must agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
