"""Real-provider smoke through the product UI (RULES §4: before any demo and weekly).

Starts the API and worker on the real configuration in `.env` (hosted Supabase, Azure Voice
Live, the D28 scoring model) plus the web app, then drives a browser exactly as a rep would:
sign in -> pick a scenario -> enable mic -> talk -> end -> wait for the scored report ->
click evidence and check the recording seeks -> latency dashboard. The rep's voice is
Windows TTS played as a fake microphone. Costs real money (~$0.15 per run at D25/D28 rates).

    services/backend/.venv/Scripts/python.exe scripts/live_smoke.py --browser msedge
Screenshots and a JSON summary land in sales-platform/docs/evidence/m1-live-<date>/.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
# Reuse the spike's TTS rep synthesiser; loaded by path because spikes/ is not a package.
_spec = importlib.util.spec_from_file_location("run_voice_spike", ROOT / "spikes" / "run_voice_spike.py")
spike = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spike)

API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:5173"
LEAD_IN_SECONDS = 9.0  # covers mic enable -> session create -> SDP relay -> connected

PRIYA_LINES = spike.REP_LINES


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:  # noqa: BLE001
            time.sleep(1)
    raise TimeoutError(url)


def shot(page: Page, out: Path, name: str, full: bool = False) -> str:
    path = out / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    return path.name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", choices=["chromium", "msedge"], default="msedge")
    ap.add_argument("--scenario", default="priya-cold-call")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--lines", type=int, default=0, help="use only the first N rep lines (cheaper run)")
    args = ap.parse_args()

    env = dotenv_values(ROOT / ".env")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "sales-platform" / "docs" / "evidence" / f"m1-live-{stamp[:8]}" / f"{stamp}-{args.browser}"
    out.mkdir(parents=True, exist_ok=True)
    work = ROOT / "var" / "live-smoke" / stamp
    work.mkdir(parents=True, exist_ok=True)

    spike.LEAD_IN_SECONDS = LEAD_IN_SECONDS
    spike.REP_LINES = PRIYA_LINES[: args.lines] if args.lines else PRIYA_LINES
    rep_wav, timeline = spike.synthesize_rep_wav(work, "Microsoft David Desktop")
    talk_seconds = timeline[-1]["end"] + spike.GAP_SECONDS
    print(f"rep audio {talk_seconds:.0f}s, {len(timeline)} lines")

    py = sys.executable
    backend_env = {**os.environ, "PYTHONPATH": str(ROOT / "services" / "backend"),
                   "RECORDING_STORE": "local", "RECORDING_DIR": str(ROOT / "var" / "recordings"),
                   "CORS_ORIGINS": WEB, "WORKER_POLL_SECONDS": "0.5"}
    # Held open for the processes' lifetime and closed in `finally`, hence no `with`.
    logs = {n: (work / f"{n}.log").open("w", encoding="utf-8") for n in ("api", "worker", "web")}
    procs = [
        subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                         cwd=ROOT, env=backend_env, stdout=logs["api"], stderr=subprocess.STDOUT),
        subprocess.Popen([py, "-m", "app.workers.main"], cwd=ROOT, env=backend_env,
                         stdout=logs["worker"], stderr=subprocess.STDOUT),
        subprocess.Popen("npx vite --host 127.0.0.1 --port 5173 --strictPort", shell=True,
                         cwd=ROOT / "apps" / "web",
                         env={**os.environ, "VITE_API_BASE_URL": API,
                              "VITE_SUPABASE_URL": env["SUPABASE_URL"],
                              "VITE_SUPABASE_PUBLISHABLE_KEY": env["SUPABASE_PUBLISHABLE_KEY"]},
                         stdout=logs["web"], stderr=subprocess.STDOUT),
    ]
    summary: dict = {"run": stamp, "browser": args.browser, "scenario": args.scenario, "screens": []}
    try:
        wait_http(f"{API}/api/v1/ready")
        wait_http(WEB)
        with sync_playwright() as p:
            launch = {"headless": not args.headed, "args": [
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-audio-capture={rep_wav}%noloop",
                "--autoplay-policy=no-user-gesture-required"]}
            if args.browser == "msedge":
                launch["channel"] = "msedge"
            browser = p.chromium.launch(**launch)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            ctx.grant_permissions(["microphone"], origin=WEB)
            page = ctx.new_page()
            console: list[str] = []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
            summary["browser_version"] = browser.version

            # 1. Sign in through the real Supabase Auth form.
            page.goto(WEB)
            summary["screens"].append(shot(page, out, "01-login"))
            page.fill("input[type=email]", env["DEV_USER_EMAIL"])
            page.fill("input[type=password]", env["DEV_USER_PASSWORD"])
            page.click("button[type=submit]")
            page.wait_for_selector("[data-testid=scenario-list] a.scenario", timeout=30_000)
            page.wait_for_selector("[data-testid=whoami]", timeout=15_000)
            summary["screens"].append(shot(page, out, "02-catalog", full=True))

            # 2. Preflight: mic permission, live level meter.
            page.click(f"[data-testid=scenario-{args.scenario}]")
            page.wait_for_selector("[data-testid=preflight]")
            summary["screens"].append(shot(page, out, "03-preflight"))
            page.click("[data-testid=enable-mic]")
            page.wait_for_selector("[data-testid=mic-meter]")
            t_click = time.time()
            page.click("[data-testid=start-call]")
            page.wait_for_selector("[data-testid=call-state]:text('Live')", timeout=30_000)
            summary["click_to_live_ms"] = int((time.time() - t_click) * 1000)
            print(f"live after {summary['click_to_live_ms']} ms")

            # 3. Let the rep script play out; capture the live transcript mid-call.
            time.sleep(25)
            summary["screens"].append(shot(page, out, "04-live-call"))
            remaining = talk_seconds - (time.time() - t_click) + 3
            if remaining > 0:
                time.sleep(remaining)
            summary["live_turns_seen"] = page.locator("[data-testid=live-transcript] li.rep, [data-testid=live-transcript] li.buyer").count()
            summary["screens"].append(shot(page, out, "05-live-call-end"))
            t_end = time.time()
            page.click("[data-testid=end-call]")

            # 4. Report: metrics first, then verified criteria.
            page.wait_for_url("**/#/report/**", timeout=60_000)
            page.wait_for_selector("[data-testid=metrics]")
            summary["end_click_to_metrics_ms"] = int((time.time() - t_end) * 1000)
            summary["screens"].append(shot(page, out, "06-report-metrics"))
            page.wait_for_function(
                "() => !document.querySelector('[data-testid=scoring-progress]') && "
                "document.querySelectorAll('[data-testid=criteria] article').length > 0",
                timeout=120_000,
            )
            summary["end_click_to_report_ms"] = int((time.time() - t_end) * 1000)
            report_id = page.url.rsplit("/", 1)[-1]
            summary["report_id"] = report_id
            summary["screens"].append(shot(page, out, "07-report", full=True))

            # 5. Evidence seek: the click must move the recording to the quote's moment.
            quotes = page.locator("[data-testid=evidence]")
            summary["evidence_quotes"] = quotes.count()
            labels = quotes.locator(".who").all_text_contents()
            summary["evidence_all_rep"] = all(lbl.startswith("You said") for lbl in labels)
            if quotes.count():
                page.wait_for_selector("[data-testid=recording]", timeout=30_000)
                page.wait_for_function("() => document.querySelector('[data-testid=recording]').readyState >= 1", timeout=30_000)
                time.sleep(1.5)
                target = quotes.nth(min(1, quotes.count() - 1))
                target.click()
                time.sleep(1.0)
                summary["seek"] = page.evaluate("""() => {
                    const a = document.querySelector('[data-testid=recording]');
                    const hit = document.querySelector('[data-testid=transcript] li.hit');
                    return { currentTime: a.currentTime, duration: a.duration, paused: a.paused,
                             highlighted: hit ? hit.className : null, ts: hit ? hit.querySelector('.ts').textContent : null };
                }""")
                summary["screens"].append(shot(page, out, "08-evidence-seek", full=True))

            # 6. Latency dashboard + integrity.
            page.goto(f"{WEB}/#/latency")
            page.wait_for_selector("[data-testid=integrity]", timeout=30_000)
            summary["integrity_text"] = page.locator("[data-testid=integrity]").inner_text()
            summary["screens"].append(shot(page, out, "09-latency", full=True))
            summary["console_errors"] = [c for c in console if c.startswith("error")][:20]
            browser.close()

        # Ground truth from the API, not the UI.
        token_req = urllib.request.Request(
            f"{env['SUPABASE_URL']}/auth/v1/token?grant_type=password",
            data=json.dumps({"email": env["DEV_USER_EMAIL"], "password": env["DEV_USER_PASSWORD"]}).encode(),
            headers={"apikey": env["SUPABASE_PUBLISHABLE_KEY"], "Content-Type": "application/json"},
        )
        token = json.load(urllib.request.urlopen(token_req))["access_token"]
        def get(path: str) -> dict:
            req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})
            return json.load(urllib.request.urlopen(req))
        report = get(f"/api/v1/reports/{summary['report_id']}")
        summary["report"] = {
            "status": report["status"], "overall": report["overall"], "provenance": report["provenance"],
            "timings": report["timings"], "metrics": report["metrics"],
            "criteria": [{"id": c["criterion_id"], "outcome": c["outcome"], "score": c["score"],
                          "verified": c["verified"], "quotes": len(c["evidence"])} for c in report["criteria"]],
            "drills": [d["id"] for d in report["drills"]],
        }
        summary["integrity"] = get("/api/v1/evidence/integrity")
        summary["latency"] = get("/api/v1/metrics/latency")
        summary["usage"] = get("/api/v1/usage/summary?days=1")
    finally:
        for proc in procs:
            proc.terminate()
        for fh in logs.values():
            fh.close()
        if sys.platform == "win32":
            subprocess.run("taskkill /F /T /FI \"WINDOWTITLE eq vite*\"", shell=True, capture_output=True,
                           check=False)
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary.get(k) for k in (
        "click_to_live_ms", "live_turns_seen", "end_click_to_metrics_ms", "end_click_to_report_ms",
        "evidence_quotes", "evidence_all_rep", "seek", "integrity")}, indent=2))
    print(json.dumps(summary.get("report", {}), indent=2)[:3000])
    print(f"evidence: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
