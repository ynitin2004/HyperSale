# Delivery Phases

## M1 checkpoint — 2026-10-29 (built; live-verified on real providers)

User authorized M1 build (quiz 2026-10-29: api-brokered voice socket D29, scoring on
`gpt-5.6-sol` D28, ~$5 live budget, hosted migrations after local round trip, pushes).
M0's last open technical gate closed the same day: **Spike 3 passed** on `gpt-5.6-sol`
(3/3 schema-valid, D13 fabricated/misattributed 0/0, ~$0.02/report).

| M1 "done when" | Status | Evidence |
|---|---|---|
| 5 personas + scenarios seeded, criteria per scenario | **Done** | `seeds/` + `catalog.json`; hosted seeded (5/5/14/rubric-v1); prompt versions content-hashed (D30) |
| Voice session: preflight → brokered WebRTC → live transcript → chunked recording upload | **Done** | D29/D32; 5 full live calls on Edge 157 + Chromium, 32–42 server-captured turns each, 19 × 10 s chunks |
| Start < 5 s | **Met** | Click → talking 3.4–3.9 s in the UI; server connect p95 1.9 s |
| Metrics < 1 s after end | **Met, one edge** | Server end->metrics on 4 AI-rep calls: **758 / 744 / 795 / 1052 ms**. p50 well under 1 s; one call at 1.05 s (hosted pooler round trips). Watch on the latency dashboard |
| Full report p95 < 30 s | **Met (2026-10-29 live, D35)** | One scoring call per report: **29.4 s / 18.7 s** live (was 31.3 / 33.7 s with 3 parallel calls). Eval harness over 34 items: scoring p95 **27.1 s**. Margin is thin on this gateway |
| Every evidence quote seeks correctly | **Met** | Click → recording at 9.0–9.7 s for turns at 0:10–0:11 (300 ms lead + recorder offset), highlighted rep turn |
| Zero DB rows fail existence or attribution | **Met** | `/evidence/integrity`: 100/100 persisted hosted quotes re-verified, 0 failing; every report `ready`, never `degraded` |
| Latency dashboard live | **Met** | `#/latency` + `/api/v1/metrics/latency` (p50/p95 vs budget per stage) |
| Rubric v1, scenario-scoped, `insufficient_evidence`, provenance | **Met** | 7 criteria; out-of-scope criteria never scored; reports carry rubric/prompt/model/metrics + persona prompt version |
| 3 drills | **Met (rule-based)** | Weakest scored criteria → seeded drills; Haiku tier (AI-2) deferred, no reachable volume model |
| Safari | **Open (D24)** | No Apple device; M1 exit gate |
| Recording storage on Supabase | **Met (2026-10-29 live)** | User approved; private `recordings` bucket (2 MB object limit). Probe: secret-key PUT 200 + read-back, public URL 400, publishable key 400. Live: call `9ebda41e` stored 17 chunks / 354 KB in the bucket; report playback and evidence seek (0:37) served from it |
| Sentry / OTel exporters | **Open (account ready)** | Sentry org `hypersaleai` created by user 2026-10-29; Sentry MCP added at local scope, needs `/mcp` sign-in. Still no DSN in `.env`; OTel endpoint unset |

Cost truth, live (hosted ledger, `/usage/summary`): voice 4 calls $0.532 (≈ $0.045/min),
scoring 12 model calls $0.492 at $4/$20 per 1M (the 2-way split wrote long outputs; the
3-way split cuts output per call). A 3-minute roleplay + report ≈ **$0.17**.

Tests: 73 unit (incl. 8 executable decision tests), 15 integration (full loop over HTTP on
Postgres, RLS per new table), 4 Playwright E2E (stub providers), 5 live UI runs. CI: GitHub
and GitLab now also run the OpenAPI/TS drift checks and the E2E job.

### Late 2026-10-29: D33 dual-model scoring, D34 AI rep, live loop

- D33 built: `SCORING_MODEL` / `SCORING_FALLBACK_MODEL` / `CLAUDE_API_KEY`; Claude Opus 5.5
  request shape (no forced tool_choice, effort medium); whole-report fallback. 7 unit tests
  (`test_scoring_fallback.py`), 80 unit total green, ruff clean. Live: Claude via the gateway
  -> 503 "no channel" -> `ScorerUnavailable` in 1.4 s (fallback path classifies correctly).
- D34 built: AI rep in `scripts/live_smoke.py` (`scripts/ai_rep.py`). Two live calls, both
  `ready`, all quotes verified, recording in the bucket:
  weak rep vs Sam (CFO negotiation) **2.2**; average rep vs Elena (inbound) **4.2** -
  scores separate good from bad calls. Traces: `CALL-TRACES.md`. Harness bugs fixed after
  call 1 (empty model reply padded with a goodbye; sentence pauses let the buyer's VAD cut
  the rep off).
- Per-call cost (ledger): voice $0.076 + scoring $0.080 (3 calls) + AI rep $0.04-0.06.
- **Blocker:** the gpt-5.6-sol key has $0.017 left; scoring needs $0.021 per call (403). The
  gateway also returned one intermittent 400 ("function tools ... not supported in
  /v1/chat/completions"). Loop stopped after 2 calls.

Remaining before M1 exit (all need the user): Safari (Apple device), Sentry `/mcp` sign-in + DSN, OTel endpoint,
demo workspace seeding, and approval of the scorer retry for the gateway's intermittent 400. M2 cannot start
engineering acceptance until **external raters** exist (D14).

## M0 closure checkpoint — 2026-10-24

User authorized full build-out on 2026-10-24 (quiz answered: scoring via gateway, Safari
deferred, ~$5 Azure spend, hosted role provisioning + pushes to both remotes). Evidence below
is from runs this session; JSON reports archived in `docs/evidence/voice-spike-2026-10-24/`.

| M0 gate | Status | Evidence |
|---|---|---|
| Monorepo, one image/two entrypoints, local stack | **Closed** | `docker compose up --build`: db healthy -> migrate exit 0 -> api healthy (/health, /ready 200) + worker running, one image (`sqlalchemy[asyncio]` pin fixed a Linux-only greenlet ImportError). |
| Alembic baseline, round-trip, schema check | **Closed** | Local up/down/up + `alembic check` clean on Docker; hosted `alembic check` clean via session pooler; 42 unit + 13 integration tests pass; Ruff clean. |
| Supabase Auth + one protected route | **Closed** | `scripts/seed_dev_user.py`: real Supabase user + workspace + owner membership; ES256 JWT -> `/api/v1/whoami` 200, no token 401, `/me` returns role. Publishable key in `.env` was stale and corrected. |
| Tenancy: restricted runtime role | **Closed** | `scripts/provision_runtime_roles.py`: `hypersale_app` NOBYPASSRLS (0 rows visible without GUC), `hypersale_worker` BYPASSRLS for dispatch only; API verified running as the app role (D26). |
| Spike 1 — cost truth | **Closed** | 169.8 s automated Priya call, 20 responses: 24,777 in / 1,375 out tokens, **$0.142 = $0.050/min** at gpt-realtime list prices. Posted through API -> queue -> worker; hosted `usage_events` row = 141,823 microusd, `rate_missing=false`; `/usage/summary` returns the same (D25). |
| Spike 2 — audio truth | **Closed (re-scoped, D24)** | Mixed mic+buyer Opus/WebM decoded in-browser: RMS rep 0.068 / buyer 0.096 vs quiet 0.019 on Chromium; 0.082 / 0.103 vs 0.010 on Edge 156. Safari deferred to an M1 exit gate (no Apple device). |
| Control-channel lifetime (adapter design) | **Answered** | 3 runs, both browsers: after `ws.close()` PC `connected`, remote track `live`, **0 further turns**. Browser must hold the WS; `api` stays stateless and mints a browser-safe credential (D23). |
| Turn latency (real client) | **Measured** | 19 turns: transcript-delta mean 203 ms; audible mean 758 ms, p95 1,087 ms; connect 2.1-5.6 s. Within budget. |
| Spike 3 — scoring call | **Open (external)** | `spikes/run_scoring_spike.py` + `adapters/llm/client.py` ready (tool-forced schema, D13 checks). Gateway: 403 for `claude-opus-5`, 503 "no channel" for `claude-opus-5-5` (D27). Needs model enablement or another credential. |
| Sentry + OTel wired | **Code present** | `telemetry.py` degrades to JSON logs without DSN/endpoint; exporters unverified (no accounts). |
| CI green on public repo | **Closed (GitHub)** | Run #6 at `8bcd5a9` failed one RLS test (dispatch factory bound at import; console in `docs/evidence/ci-2026-10-24/`). Fixed in `0b5b923`; run #7 (40086352860): backend, web, image all success. GitLab mirrors the same jobs; its console needs a `read_api` token to archive. |
| External raters (gates M2) | **Open (human)** | Not started; user action. |

M0 is closed on every gate the solo build can close itself. Two items remain external:
a working scoring model (credential) and rater recruitment. **M1 is cleared to start**, with
its first task fixed by D23: a browser-safe Azure Voice Live credential minted by `api`.

## Progress checkpoint — 2026-10-24 (read-only audit)

Verified via Supabase MCP (read-only) and local commands; no code, hosted data, or Git changed.
- Hosted DB at head `20260824_0002`; 4 M0 tables ENABLE+FORCE RLS. **0 rows** in every table,
  **0 `auth.users`**. `postgres` runtime role still BYPASSRLS; no restricted app role exists.
- `usage_events` empty: Spike 1 (cost truth) has never written a costed row. Spike 3 (scoring)
  still blocked on API access. Audio truth still lacks Chrome/Safari playback + drop evidence.
- Unit tests 39 passed, Ruff clean. Backend app is 1,779 LOC; `scoring/` and `review/` are
  docstring stubs; `practice/api.py` still mints OpenAI sessions (D21 Azure adapter unbuilt).
- Working tree: 13 files uncommitted since a6edbbc; last hosted CI run failing; no push authorized.
- Estimate: M0 ~60% (gates 1–6 above open), M1 ~10% (1/5 personas, fixture, protocol seam only),
  M2 0% and blocked on M1. Earliest M2 start ~4–5 weeks if M0 closes this week and M1 holds to
  the 3-week plan. Rater recruitment and a working scoring API key are the two items to start now.

## Progress checkpoint — 2026-10-16

Gateway diagnosis clarified (2026-10-16): user's Agent Router screenshot shows
token enabled and allowed model ID `claude-opus-5-5`. Both bearer and Anthropic-header
model-list probes return `unauthorized_client_error` / "unauthorized client detected".
Earlier 401s did not establish an invalid key; gateway client access is blocked.
Need provider confirmation of supported application clients/API endpoint. No paid inference,
provider integration, model switch, credential persistence, or push performed.

Gateway recheck (2026-10-16): replacement key described by user as "opus 5-5"
returned HTTP 401 from GET /v1/models on both documented Agent Router hosts.
No credential saved, paid inference, or model switch. Need the exact API base URL
and model ID from the user's Agent Router dashboard; scoring gate remains open.

### User-supplied live voice evidence - 2026-10-16

- Azure signalling and WebRTC connected; remote audio track, data channel, and Opus WebM
  recorder started. Ten measured turns; recording saved (reported 1252 KB). Browser/version
  and both-voice playback not yet explicitly confirmed.
- Reported samples: 134, 138, 120, 187, 139, 147, 117, 133, 161, 148 ms; mean 142.4 ms.
  These are speech_stopped-to-first-transcript/text-delta measurements from the harness,
  NOT verified time to audible response or voice p95 acceptance. No audio-onset metric exists.
- Log shows normal disconnect/WS closure at 03:05:51 after last turn at 03:05:48. It has
  no explicit Drop signalling WS / KEEP TALKING marker or subsequent responses, so
  control-channel independence remains unproven. Do not pick adapter lifecycle yet.
- Pending: playback confirmation for both voices, explicit signalling-drop-then-conversation
  test, Safari run, audible latency measurement, timed usage/cost and scoring spike. M0 open.

### Latest result: approved DB repairs and migrations complete

- Corrected `.env` database credentials with URL encoding. Both pooler and direct Supabase
  connections succeeded. Runtime uses transaction pooler; new optional `ALEMBIC_DATABASE_URL`
  selects the verified direct connection, with safe percent escaping in Alembic config.
- Split SQL batches in 0001/0002, preserving SQL content/order, revision IDs and schema.
  Fixed integration-fixture password masking. Fresh local upgrade/downgrade/upgrade,
  `alembic check`, all **52 tests (39 unit + 13 integration)**, and Ruff pass.
- User explicitly authorized migrations. Applied existing migrations to the verified empty
  Supabase project: **20260824_0002 (head)**; hosted `alembic check` passes. No hosted
  downgrade, remote Git push, or deployment. Hosted four M0 tables have ENABLE/FORCE RLS.
- API TestClient with hosted runtime configuration: health 200, readiness 200, missing-auth
  whoami 401. This is not an authenticated end-to-end product login test.
- Existing hosted postgres runtime credential has BYPASSRLS; provisioning a restricted
  runtime role remains a separate task before production use. Local isolation tests do use
  an unprivileged role; do not confuse those with hosted runtime isolation.
- Chrome file-launch command succeeded. Started a localhost-only, spike-directory-only
  server at `http://127.0.0.1:8765/voice-live-webrtc.html` (PID 30024); HTTP 200 confirmed.
  Later attempt to open localhost in Chrome was policy-blocked. No live microphone test run.
- User identified key issuer as Agent Router. Model-list checks against agentrouter.org
  and current documented co.agentrouter.org returned 401. No gateway credential saved,
  paid inference performed, provider integration implemented, or model registry changed.
- Supabase MCP tools still not exposed in this conversation despite user's reload; actual
  database work used verified direct SQL connections and repository Alembic migrations.

M0 still open: live signalling-drop, Chrome/Safari recording, measured latency/cost, scoring
spike/API access, auth login/runtime-role verification, telemetry wiring and hosted CI after an
authorized push. Earlier failure rows below are historical and superseded by this result.

Reviewed local Claude session history (latest substantive exchange 2026-09-23),
Claude project memory, git through `a6edbbc`, and current source. This is a source
audit followed by local diagnostics below. Live Azure/Safari acceptance and provider
billing remain untested.

| Phase | Status | Evidence and remaining gates |
|---|---|---|
| M0 | Closed 2026-10-24; Spike 3 passed 2026-10-29 (raters still external) | See the closure checkpoint above: cost $0.050/min measured and ledgered, audio truth on Chromium/Edge, control channel answered, auth + restricted role verified, local stack and tests green. |
| M1 | Built and live-verified 2026-10-29; exit gates open | See M1 checkpoint above: full loop live on Azure + gpt-5.6-sol + hosted Supabase; latency fixes to re-measure; Safari, storage bucket, Sentry/OTel open. |
| M2 | Not demonstrated | No implemented eval harness or manager loop found; external rater recruitment unconfirmed. |
| M3 | Not implemented | Review module is a placeholder; recording pipeline remains planned. |
| M4 | Not implemented | Commercial surface and acceptance checks remain planned. |
| M5 | Not implemented | AWS migration remains deferred. |

Immediate next steps:
1. Verify the exact Supabase connection settings; the active URL has a password, but
   the pooler rejects the configured tenant/user after URL-encoding was corrected.
2. Run `spikes/voice-live-webrtc.html`: drop signalling WS and report whether audio survives;
   save mixed recording and verify both voices on Chrome and Safari; capture turn latency.
3. Use those results to decide Azure adapter lifecycle before implementation (major-change quiz applies).
4. Measure a timed real call and scoring fixture cost; a historical total charge is insufficient.
5. Confirm CI results, local stack, and rater recruitment; close M0 only with acceptance evidence.

D21 selects Azure Voice Live. Older OpenAI-direct wording below describes the original
plan and must be reconciled when the Azure path is implemented. Current practice API
still calls OpenAI directly; the VoiceProvider protocol has no concrete Azure implementation.
Update this checkpoint after every task with what changed, checks run, and open gates.

### Executed diagnostics — 2026-10-16

Follow-up setup checkpoint:
- User-supplied Claude credential failed the official Anthropic model-list endpoint with
  HTTP 401 / authentication_error. It was not stored. No inference or scoring call was made.
  Need a replacement official Anthropic credential, or identification of its actual issuer
  and API endpoint. User referred to Opus 4.8; documented Opus 5 selection remains unchanged
  pending verified access and an explicit model decision.
- CLI still confirms Supabase MCP enabled and OAuth authenticated. The separate ChatGPT
  Supabase plugin is not installed; local CLI authentication does not expose MCP tools in
  this already-running conversation. Reload the Codex session before schema inspection.
- Requested Chrome launch for the local voice spike and Supabase dashboard was rejected by
  automatic approval review as blocked by policy. No interactive browser testing occurred.
- User must open the spike in Chrome, supply the Azure key locally, allow microphone access,
  and report signalling-drop, both-voice playback, and latency results; repeat on Safari.
- No cloud push, deployment, or hosted DB mutation is permitted without explicit user approval.
  Migration/test-fixture repairs are still awaiting permission; M0 acceptance remains open.

| Check | Result / evidence |
|---|---|
| Backend unit tests | 39 passed (`pytest -q --ignore=tests/integration`). |
| Backend lint | `ruff check .` passed. |
| Frontend builds | `corepack pnpm@9.15.0 -r build` passed for React and Astro. Bare Corepack invocation fails with its installed signing-key metadata; explicit pinned invocation works. |
| Local DB | Started Docker Desktop and existing compose Postgres service; healthy. |
| Online migrations | Reproduced failure in 0001: asyncpg rejects multiple commands in a prepared statement. No migration files edited. |
| Independent schema check | Rendered existing migrations offline and applied their SQL to local DB only; `alembic check` reports no new operations. This does NOT pass online migration/rollback acceptance. |
| Integration tests | 7 passed, 6 failed. Failing tests cannot authenticate the unprivileged test role because `str(URL)` masks the fixture password as `***`; tenancy assertions remain unverified. No fixture/auth changes made. |
| Latest public GitHub CI | Run 35901907546 at `a6edbbc`: image passed; backend migration step failed; web setup failed on conflicting pnpm versions. Working-tree CI fix removes GitHub version override and pins GitLab via package.json. Not pushed or verified in hosted CI. GitLab public API returned 404; its status is unknown. |
| Supabase connection | Existing project-local Codex config set to read-only; OAuth login completed and CLI reports `o_auth`. Tools are not exposed in this already-running conversation; no hosted schema queries or writes performed through MCP. |
| Hosted DB | URL-encoded reserved credential characters in ignored `.env`, preserving password value. DNS parsing now succeeds; pooler responds tenant/user not found. Exact dashboard connection settings still needed. |
| Chromium recording smoke | Installed Playwright Chromium and ran existing spike in headless mode with synthetic 440/880 Hz source tracks. Opus WebM recording decoded with both tones present (16,583 bytes). No Azure traffic or real microphone; not Chrome/Safari live acceptance. |

Remaining M0 gates: repair online migrations and test fixture after explicit permission;
verify hosted DB settings; rerun migrations round-trip/integration/CI; run real signalling-drop,
mic+buyer recording on Chrome and Safari, latency and timed-cost measurement; complete scoring
spike (ANTHROPIC_API_KEY absent); confirm external raters. User explicitly requested reporting
issues before repairs. Phase remains M0 in progress; M1 is not cleared to start.

Every milestone carries: functional acceptance, security checks, tests at all four levels, AI
evals (from M2), rollout flags, and maintenance (dependency updates, backup check, MEMORY.md
update). Timeline assumes solo, ~full-time.

## M0 — Week 1: Skeleton, cost truth, audio truth

- Monorepo; one Dockerfile, two entrypoints; Supabase project; Alembic baseline; Supabase Auth +
  one protected route; GitHub Actions CI on a public repo (D18); Sentry + OTel wired; asyncpg
  pooler config (`statement_cache_size=0`).
- **Spike 1 — cost truth (first, before product code):** one real 3-minute Realtime voice call;
  write actual audio/token usage + computed cost to `usage_event`. This number sets session caps,
  trial limits, and pricing.
- **Spike 2 — audio truth (same week):** mix remote WebRTC track + mic via Web Audio, record with
  `MediaRecorder`, play it back — **verified on Chrome and Safari**. Fails → adopt mic-only
  fallback (ARCHITECTURE.md §4) and record the decision.
- **Spike 3 — scoring call:** one Claude Opus 5 structured-output call against a fixture
  transcript returning schema-valid rubric JSON; log tokens + cost to `usage_event`.
- Start recruiting 2–3 external sales-manager raters (longest-lead item; gates M2).
- **Done when:** cost per roleplay minute and per report are known numbers, audio path proven or
  fallback chosen, `docker compose up` gives a working local stack, CI green on a public repo.

## M1 — Weeks 2–4: The roleplay loop (the demo)

- 5 hand-crafted personas + scenarios seeded via script (no builder UI), each declaring its
  applicable criteria.
- Voice session: preflight (DESIGN.md audio playbook) → ephemeral token mint → WebRTC → live
  transcript over SSE (turns + speakers preserved) → chunked recording upload.
- Scoring: rubric v1, scenario-scoped, `insufficient_evidence` outcome, deterministic metrics,
  existence + attribution verification, full provenance.
- Report page: metrics instantly, criteria streamed, transcript with timestamped evidence, audio
  player seeking to any quote, 3 drills.
- **Done when:** start < 5 s; metrics < 1 s; full report p95 < 30 s; every evidence quote seeks
  correctly; zero rows in the DB fail existence or attribution; latency dashboard live.

## M2 — Weeks 5–6: Evals + manager loop *(this milestone is the interview)*

### M2 checkpoint - 2026-10-29/30 (quiz: text sims + live, rater page + provisional baseline, paid eval only on scoring changes)

| M2 "done when" | Status | Evidence |
|---|---|---|
| Gold set >= 30 transcripts | **Built (34)** | 30 text sims (5 scenarios x 3 rep skills x 2) + 4 live AI-rep calls, `services/backend/evals/goldset/` (D36) |
| Labelled by external raters, rater agreement first | **Open - needs humans (D14)** | Rater page `#/rate` built and tested (blind, own labels, Evals workspace, D37). Provisional ceiling from two model raters: QWK **0.850**, MAE 0.37 - marked `model-provisional`, does not close M2 |
| Eval harness in CI (kappa + MAE vs ceiling, fabricated/misattributed = 0, IE rate, latency, cost) | **Built** | `python -m evals.harness`; product run: QWK **0.909** / MAE 0.22 vs consensus, 0 fabricated, 0 misattributed, IE 5.3% vs 4.2%, p95 27.1 s, $1.22 for 34 items. Free replay on every CI run; paid job on scoring-path changes (D38) |
| A deliberately degraded prompt demonstrably fails | **Met (provisional)** | Same 8 items: unchanged prompt PASS (noise 0.053 kappa); lenient prompt FAIL (0.938 -> 0.839, MAE 0.15 -> 0.35); inverted-scale bug FAIL (kappa -0.35). Runs in `evals/runs/` |
| Manager: assign scenario, review attempts, team comparison | **Built, CI green** | Migration 0004, `coaching` module, `#/team`, Home "Assigned to you" (D39). GitHub CI run 40935415366 at bd7efcf: migration up/down/up + `alembic check`, M2 integration tests, E2E team + rater tests all green. **Hosted migration not applied** (rule: local round trip first; Docker down, local Postgres binaries blocked) |

Caveat: the provisional raters and the scorer are the same model, so model-vs-consensus beating
the ceiling (0.909 > 0.850) is expected and is **not** evidence of human-level agreement.

- Gold set: ≥30 transcripts labeled by the external raters; inter-rater agreement computed
  **first** (the ceiling).
- Eval harness in CI: weighted kappa + MAE vs labels against the ceiling; fabricated- and
  misattributed-quote rates (must be 0); sampled evidence relevance; `insufficient_evidence`
  rate; persona fidelity; p95 latency; cost per run. Prompt/model changes that regress → build fails.
- Manager: assign scenario, review attempts, team comparison.
- **Done when:** agreement numbers publishable with their ceiling; a deliberately-degraded prompt
  demonstrably fails CI.

## M3 — Weeks 7–9: Recording review

- Upload → Postgres queue → `Transcriber` (diarize + word timestamps + turns) → **same scoring
  path as M1**. Idempotent retries; visible failure states; SSE progress. Zoom only if a design
  partner asks.
- **Done when:** one pipeline serves roleplays and real calls; a worker killed mid-job resumes
  without duplicate work or double-charging.

## M4 — Weeks 10–12: Commercial surface, behind flags

- Invites, roles, consent + retention settings, audit log, retention-deletion job (provably
  removes audio from storage). Metering + plan limits before billing; Stripe only when someone
  asks to pay.
- **Done when:** `test_tenancy.py` green on every table; deletion verified against storage.

## M5 — AWS migration

Terraform + env-var exercise per ARCHITECTURE.md §9. Fargate/App Runner; no EKS without a
documented trigger. Record scale criteria in DECISIONS.md before moving.

## Verification commands (all local, offline against docker compose)

| Level | Command |
|---|---|
| Unit/schema | `pytest services/backend` |
| API + permissions | `pytest -m integration` (throwaway Postgres container) |
| E2E | `pnpm playwright test` (stubbed voice provider — no live API cost) |
| AI evals | `python -m evals.harness --suite roleplay` |
| Pre-demo smoke | One real 3-min roleplay; check `usage_event`, Sentry, evidence seeks, phone rendering |
