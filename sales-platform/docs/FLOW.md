# FLOW — Entry Points, Execution Order, AI Decision Points

Living map of how the code runs. **Every PR that adds or changes an execution path updates this
file** (RULES.md §1). Status: written ahead of code (M0 not started) — chains below are the
planned shape; correct them as code lands and mark each chain `[verified]` once it matches
reality. The migration and database setup chain below is verified as of 2026-10-16;
the product roleplay/scoring chains remain planned.

### Verified chains (2026-10-24)

**Boot.** `services/backend/app/main.py` -> `setup_telemetry` (JSON logs always; Sentry/OTel
only with DSN/endpoint) -> `app/db/session.py` builds the runtime engine from `DATABASE_URL`
(hypersale_app, transaction pooler 6543) and a dispatch engine from `WORKER_DATABASE_URL`
(hypersale_worker, BYPASSRLS; D26). `/health` liveness, `/api/v1/ready` touches the DB.

**Auth -> protected route.** Supabase Auth password sign-in -> ES256 JWT -> `HTTPBearer` ->
`TokenVerifier` (JWKS cache) -> `identity_session` + `resolve_membership` -> `Principal` ->
`/api/v1/whoami`, `/api/v1/me`. Verified against the hosted project with a seeded user
(`scripts/seed_dev_user.py`): 200 with a token, 401 without.

**Usage metering (money path, M0 Spike 1).** Browser (or `scripts/report_spike_usage.py`)
-> `POST /api/v1/practice/realtime/usage` with the six `response.done.usage` token buckets ->
`enqueue` (idempotency `realtime-usage:<session_ref>`) -> 202 -> worker `system_session`
claims -> `tenant_session(workspace)` -> `record_realtime_usage` -> `realtime_token_cost`
(D25) -> `record_usage` (dedupe `realtime:<session_ref>`) -> hosted `usage_events` ->
`GET /api/v1/usage/summary` (manager role). Verified end to end: 141,823 microusd in the
ledger equals the spike's own computation.

**Migrations.** Alembic -> `ALEMBIC_DATABASE_URL` (session pooler 5432 as `postgres`) ->
0001 -> 0002, one statement per execution (D22). Local up/down/up + `alembic check` and
hosted `alembic check` pass; 13 integration tests run as an unprivileged role on Docker.

**Local stack.** `docker compose up --build` -> db (healthy) -> `migrate` (PROCESS_ROLE) ->
`api` + `worker` from the one image, local URLs pinned so `.env` hosted URLs cannot leak in.

**Voice spike (not product code).** `spikes/run_voice_spike.py` -> SAPI TTS rep WAV -> Chromium/
Edge fake mic -> `spikes/voice-live-webrtc.html` -> Azure Voice Live WebRTC + signalling WS ->
events, mixed recording, latency, usage -> `report.json` (archived in `docs/evidence/`).
Findings feed D23/D24/D25.

**Scoring spike (blocked).** `spikes/run_scoring_spike.py` -> `adapters/llm/client.py`
(official SDK, `ANTHROPIC_BASE_URL`) -> tool-forced rubric JSON -> D13 existence +
attribution checks. Gateway currently returns 503/403 (D27); no score has been produced yet.

## 0. Onboarding pass (adapted from the "staff engineer" prompt)

When a session needs to rebuild context and this file is stale, run this against the repo —
goal is a mental model, not code changes:

> You are a staff engineer joining this project. Do not modify code. Using docs/ as the claimed
> architecture, verify it against reality: walk the tech stack and versions; map the two deploy
> units and eight modules; identify every entry point (HTTP routers, worker entrypoint, cron);
> trace one full request from the SPA through `WorkspaceContext` to Postgres and back; trace one
> job from enqueue to SSE completion; **trace the full latency path of a voice session and the
> full audio pipeline (mic → WebRTC → recorder → chunked upload), since latency and audio
> reliability are this product's top risks**; list every external integration (Supabase, Upstash,
> OpenAI Realtime, Anthropic, Resend, Sentry, PostHog) and where each is wrapped in `adapters/`;
> check config/secrets handling; flag drift between code and docs/; then repair FLOW.md and list
> the 10 files a new dev should read first.

## 1. Entry points

| Entry point | File (planned) | Triggers |
|---|---|---|
| HTTP API | `services/backend/app/main.py` (uvicorn; `/health`, `/api/v1/*`) | All SPA calls, webhooks |
| Worker | `services/backend/app/workers/main.py` (`python -m`) | Claims jobs from Postgres queue |
| SPA | `apps/web/src/main.tsx` → TanStack Router | Browser |
| Migrations | `alembic upgrade head` | Deploy step |
| Evals | `python -m evals.harness` | CI on prompt/model change; manual |
| Seeds | `scripts/seed_dev_user.py` (auth user + workspace); persona seeds planned | Local dev, demo workspace |
| Ops scripts | `scripts/provision_runtime_roles.py`, `scripts/report_spike_usage.py` | Hosted role setup; pushing spike usage through the ledger |
| Spikes | `spikes/run_voice_spike.py`, `spikes/run_scoring_spike.py` | M0 evidence runs (not product code) |

## 2. Execution chains (planned order — verify as built)

### A. App boot
`main.py` → load settings (env, fail fast on missing) → init OTel + Sentry → build engine
(asyncpg, `statement_cache_size=0`) → mount routers → healthcheck `/healthz`.

### B. Voice roleplay session (the money path)
1. `POST /sessions` (practice) → `WorkspaceContext` → `practice.service.start_session` →
   creates `practice_session` row + **mints ephemeral Realtime token** via `adapters/voice/` →
   returns token + session id. *(≤ 300 ms budget)*
2. Browser: preflight (DESIGN.md §4) → WebRTC connect **directly to Azure Voice Live**, holding the signalling WS for the call's lifetime (D23) → conversation.
3. Browser → `POST /sessions/{id}/transcript-events` (batched): `practice.service.ingest_events`
   → append transcript turns (speaker + timestamps) → fan out to SSE `GET /sessions/{id}/stream`.
4. Browser → chunked recording upload to signed storage URLs (parallel, independent).
5. `POST /sessions/{id}/end` → `practice.service.end_session` → compute deterministic metrics
   (pure code, < 1 s) → **enqueue scoring job in the same transaction**.
6. Worker claims job → `scoring.service.score_session` (see chain C) → progress + criteria
   streamed over the same SSE channel → report ready.

### C. Scoring (crown jewel)
`scoring.service.score_session` → load transcript + scenario's applicable criteria + frozen
rubric/prompt versions → **[AI-1]** Claude Opus 5 structured-output call (cached rubric prefix) →
for each criterion: schema-validate → **verify evidence existence** (normalized match) →
**verify speaker attribution** (span within correct speaker's turns) → any failure: retry with
feedback (cap 2), else mark degraded → persist scores with provenance
`(rubric_version, prompt_version, model_id, metrics_version)` → **[AI-2]** Haiku 4.5 drill
selection → write `usage_event` (tokens, cost) → emit `report.ready`.

### D. Recording review (M3)
`POST /recordings` (signed upload) → enqueue → worker: `review.service.process` →
`adapters/transcription/` (diarize, word timestamps) → normalize to our transcript schema →
**same chain C** → notify.

## 3. AI decision-point registry

Every place where model output influences behavior, with its guardrail. Adding one without
registering it here fails review.

| ID | Where | Model | Output | Guardrail |
|---|---|---|---|---|
| AI-1 | `scoring/` criterion scores + evidence | `claude-opus-5` | Strict JSON schema | Existence + attribution verified in code; provenance; retry-then-degrade; eval-gated in CI |
| AI-2 | `scoring/` drill recommendations | `claude-haiku-4-5` | Choice from seeded drill catalog only | Cannot invent drills; invalid id → fallback to rule-based pick |
| AI-3 | Live buyer persona | Azure Voice Live `gpt-realtime` (D21) | Speech | Persona instructions only; **no tools in hot path**; session cap server-side; transcript logged for later audit |
| AI-4 (M3) | `review/` call tagging/metadata | `claude-haiku-4-5` | Enum tags | Schema-constrained; tags advisory, never gate anything |

Standing rule: no AI output ever directly controls billing, certification, or data deletion.

## 4. What calls what — dependency direction

`api / workers` → `modules/*` → `adapters/*` + `db/`. Modules never import each other's
repositories (service-level calls + events only); `adapters` never import `modules`;
nothing imports `api`.
