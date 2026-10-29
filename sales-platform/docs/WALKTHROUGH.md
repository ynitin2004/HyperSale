# WALKTHROUGH - running and verifying HyperSale (M0 + M1)

Written for a developer (or interviewer) with the repo, Docker Desktop and a filled `.env`.
Every step below was executed on 2026-10-24; expected output is quoted from those runs.
Nothing here needs a browser you drive by hand - the spikes drive Chromium/Edge themselves.

## 0. Prerequisites

- Python 3.12 venv at `services/backend/.venv` with `pip install -e '.[dev]'` plus
  `playwright python-dotenv` and `python -m playwright install chromium`.
- Docker Desktop running. Node 20 + `corepack pnpm@9.15.0` for the web apps.
- Root `.env` from `.env.example`: Supabase URL/keys, `DATABASE_URL` (transaction pooler),
  `ALEMBIC_DATABASE_URL` (session pooler, port 5432 - the direct host is IPv6-only, D26),
  `AZURE_VOICE_LIVE_*`, and the `REALTIME_*_MICROUSD_PER_1M` rates. Scoring needs
  `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` (+ `ANTHROPIC_BASE_URL` for a gateway).
- Windows note: `pydantic-settings` reads `.env` relative to the current directory. Run
  scripts from the repo root; for Alembic from `services/backend`, export
  `ALEMBIC_DATABASE_URL` explicitly.

## 1. Local stack in one command

```
docker compose up --build
```

`db` becomes healthy, `migrate` runs `alembic upgrade head` and exits 0, then `api` (port
8000) and `worker` start from the same image. Check:

```
curl http://127.0.0.1:8000/health          -> {"status":"ok","request_id":"..."}
curl http://127.0.0.1:8000/api/v1/ready    -> {"status":"ok","database":true}
curl http://127.0.0.1:8000/api/v1/config   -> auth_configured / realtime_configured flags
curl -i http://127.0.0.1:8000/api/v1/whoami -> 401 missing_token
```

The compose services pin local Postgres URLs, so a hosted URL in `.env` cannot be touched.

## 2. Tests, lint, migrations (what CI runs)

From `services/backend`:

```
.venv/Scripts/python -m ruff check . ../../scripts ../../spikes      -> All checks passed!
.venv/Scripts/python -m pytest -q --ignore=tests/integration          -> 73 passed (incl. 8 decision tests)
set DATABASE_URL / ALEMBIC_DATABASE_URL / TEST_DATABASE_URL to postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale_test
.venv/Scripts/python -m alembic upgrade head && downgrade base && upgrade head
.venv/Scripts/python -m alembic check                                 -> No new upgrade operations detected.
.venv/Scripts/python -m pytest -q tests/integration                   -> 15 passed (unprivileged role, RLS enforced,
                                                                         full M1 loop over HTTP)
```

Use a database the compose stack does not run against (`CREATE DATABASE hypersale_test` once
on the compose Postgres). The compose `worker` polls `hypersale` every second and will claim
or requeue the queue tests' jobs, which shows up as flaky `test_queue_db` failures.

## 3. Hosted Supabase: roles, auth user, protected route

```
python scripts/provision_runtime_roles.py
  hypersale_app: created; verify={'bypassrls': False, 'rows_without_guc': 0, 'ok': True}
  hypersale_worker: created; verify={'bypassrls': True, ..., 'ok': True}
```

Rewrites `DATABASE_URL` (app role) and adds `WORKER_DATABASE_URL` in `.env`; backup kept
as `.env.bak-<stamp>`. Then, with the API running against the hosted DB
(`uvicorn app.main:app --app-dir services/backend` from the repo root, plus
`python -m app.workers.main` with `PYTHONPATH=services/backend`):

```
python scripts/seed_dev_user.py --api http://127.0.0.1:8000 --token-out %TEMP%\hypersale_dev_token.json
  auth user <uuid> in workspace <uuid>; token expires_in=3600s
  GET /api/v1/whoami -> 200 {"user_id":"...","workspace_id":"..."}
  GET /api/v1/whoami (no token) -> 401
```

## 4. Voice spike: cost truth, audio truth, control channel, latency

```
python spikes/run_voice_spike.py --browser chromium --drop-after 999 --max-seconds 240
python spikes/run_voice_spike.py --browser msedge   --drop-after 2   --max-seconds 60
```

Each run synthesises an 11-line rep script with Windows TTS, plays it as a fake microphone
into `spikes/voice-live-webrtc.html`, talks to Priya on Azure Voice Live, and writes
`spikes/runs/<stamp>-<browser>/report.json` (archived copies live in
`docs/evidence/voice-spike-2026-10-24/`). Expected shape, from the 2026-10-24 runs:

| Measure | Result |
|---|---|
| Session | 169.8 s, 20 responses, 0 errors |
| Tokens | 24,777 in (14,400 cached text, 7,488 cached audio) / 1,375 out |
| Cost | $0.142 -> **$0.050 per talking minute** |
| Latency | transcript delta mean 203 ms; audible mean 758 ms, p95 1,087 ms |
| Audio truth | both voices present (RMS rep 0.068, buyer 0.096, quiet 0.019) |
| Control channel | 0 turns after the signalling WS drop; PC still `connected` (D23) |

Push the measured usage through the real ledger path and read it back:

```
python scripts/report_spike_usage.py --run spikes/runs/<stamp>-chromium --token %TEMP%\hypersale_dev_token.json
  POST /api/v1/practice/realtime/usage -> 202 {"job_id":"...","accepted":true}
curl -H "Authorization: Bearer <token>" "http://127.0.0.1:8000/api/v1/usage/summary?days=1"
  {"total_cost_microusd":141823,"rate_missing":false,...}
```

The worker's figure must equal the spike's `cost.total_microusd`; on 2026-10-24 it did.

## 5. Scoring spike (currently blocked by the gateway)

```
python spikes/run_scoring_spike.py                     # SCORING_MODEL from adapters/llm/models.py
python spikes/run_scoring_spike.py --model claude-opus-5-5
```

Runs one tool-forced structured-output call against
`tests/fixtures/transcripts/priya_cold_call_01.json`, then applies the D13 checks
(fabricated and misattributed quote counts must both be 0) and prints tokens and cost.
On 2026-10-24 the Agent Router token returned 403 for `claude-opus-5` and 503 "no available
channel" for `claude-opus-5-5` (D27); the spike exits 1 and records the exact error.

## 6. Web shell

```
corepack pnpm@9.15.0 -r build
corepack pnpm@9.15.0 dev:web      # http://localhost:5173, "Check M0 gates" calls the API
```

## 7. Where the evidence lives

`docs/PHASES.md` (gate table), `docs/evidence/`, `docs/DECISIONS.md` D23-D27, hosted
`usage_events` / `jobs` rows in the dev workspace, and the CI runs on GitHub/GitLab.

---

# M1 — the roleplay loop

## 8. Catalog and hosted schema

```
cd services/backend && ALEMBIC_DATABASE_URL=<session pooler> .venv/Scripts/python -m alembic upgrade head
python -m app.modules.catalog.seed     (from the repo root)
  catalog seeded: {'personas_new': 5, 'scenarios': 5, 'drills': 14, 'rubric_new': 1}
```

Re-running the seed is a no-op; editing a persona prompt creates a new `prompt_version` row;
changing `rubric-v1` criteria fails loudly (D16, D30). In Docker, the `migrate` role runs both.

## 9. Browser E2E with stub providers (no spend, D31)

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/hypersale_e2e python scripts/e2e_setup.py
cd apps/web && E2E_PYTHON=<absolute path to the backend venv python> pnpm exec playwright test
  ok 1 signed-out visitors see the sign-in form, not the app
  ok 2 catalog shows five scenarios with one highlighted to try first
  ok 3 a full roleplay produces a verified, speaker-labelled report
  ok 4 latency dashboard and evidence integrity reflect the calls made
```

Playwright starts the API, the worker (health port 8766) and a built SPA itself. On Windows,
pass `E2E_PYTHON` as an absolute, quoted path.

## 10. The real thing, through the UI (paid, ~$0.25-0.30 per AI-rep run)

```
python scripts/live_smoke.py --browser msedge                  # AI rep, random scenario + skill (D34)
python scripts/live_smoke.py --skill strong --scenario sam-cfo-pricing --seed 42   # reproduce a draw
python scripts/live_smoke.py --scripted --lines 3             # old fixed rep, 1-minute call
```

The AI rep (gpt-5.6-sol via the adapter client) waits for the buyer's audio to go quiet,
writes its next line, and speaks it through a Web Audio microphone, so each call differs.
Expect 3-6 s pauses while it thinks. Every run appends a row to `docs/CALL-TRACES.md` and
writes the full transcript, scores and rationale to `docs/evidence/call-traces/<run>.md`.
With `RECORDING_STORE=supabase` in `.env`, the recording goes to the private `recordings`
bucket and the trace says so.

What it does, step by step, with the screenshot it saves to
`docs/evidence/m1-live-<date>/<run>/`:

| Step | Screen | What to look for |
|---|---|---|
| Sign in with the dev user (real Supabase Auth) | `01-login.png` | Form, no app content before sign-in |
| Scenario catalog | `02-catalog.png` | Five scenarios, Elena highlighted "Try this first", recent calls with scores |
| Preflight | `03-preflight.png` | Brief, scored criteria, Enable microphone, level meter |
| Live call (scripted mode only) | `04-live-call.png` | `Live`, elapsed / 5:00 cap, mic meter, live transcript from the data channel |
| End of call | `05-live-call-end.png` | Full transcript, End call |
| Report, first second | `06-report-metrics.png` | Metrics strip before any model output; scoring progress banner |
| Scored report | `07-report.png` | Overall, per-criterion scores, rationale, rep-labelled quotes, 3 drills, provenance footer |
| Evidence click | `08-evidence-seek.png` | Highlighted rep turn; the recording seeks to that moment |
| Latency dashboard | `09-latency.png` | p50/p95 vs budget per stage; evidence integrity "0 failing" |

`summary.json` records the measured numbers and the API's own view of the report, usage and
latency, so the screenshots can be checked against ground truth.

## 11. Decision tests

```
cd services/backend && .venv/Scripts/python -m pytest -q tests/test_decisions.py
```

Each test enforces one recorded decision (provider SDKs only in adapters, model IDs only in
`models.py`, no credentials in the SPA, one statement per migration execute, FORCE RLS on
tenant tables, bounded browser usage, no spoofed client identity). The full map from
decision to guard is `DECISION-TRACES.md`.

## 12. M2: gold set, raters, eval gate, manager loop

Run from the repo root with the backend on `PYTHONPATH` (`services/backend`), `.env` present.

```
python -m evals.goldset simulate --per-cell 2     # paid: ~30 text sims (5 scenarios x 3 skills x 2)
python -m evals.goldset import-live               # every live AI-rep call trace
python -m evals.model_rater --rater strict-vp --rater enablement-lead   # PROVISIONAL labels (D36)
python -m evals.harness --suite roleplay          # paid: score every item, write evals/runs/, gate
python -m evals.harness --suite roleplay --replay # free: gate the committed latest run (CI does this)
python -m evals.harness --suite roleplay --prompt-variant degraded --limit 8   # must FAIL
```

The harness prints the ceiling kind. `model-provisional` means no human labels yet: the numbers
are useful for regressions but **do not close M2** (D14).

Human raters (D37), after migration 0004 is on the hosted database:

```
python scripts/eval_labels.py import-items          # gold set -> "HyperSale Evals" workspace
python scripts/eval_labels.py add-rater --email someone@example.com   # prints a one-time password
# rater signs in -> "Label" tab -> scores each call blind -> Save and next
python scripts/eval_labels.py export                # -> evals/labels/human-<n>.json; commit them
```

With two or more `human-*.json` files the harness switches to the human ceiling automatically.

Manager loop (D39), as a manager or owner: **Team** tab shows each member's attempts, mean
overall and mean per criterion; click a member to review their attempts; the form assigns a
scenario with an optional due date. Reps see "Assigned to you" on Practice; an assignment turns
`done` when they finish that scenario with a scored report.
