# Architecture

Modular monolith. One codebase, one Docker image, **two deploy units**: `api` (request/response,
must stay warm) and `worker` (long jobs, retries, backoff). Eight internal modules with hard
boundaries. Full rationale for every choice: `DECISIONS.md`.

## 1. Stack

| Layer | Choice |
|---|---|
| App frontend | Vite + React 19 + TanStack Router + TanStack Query + Tailwind + shadcn/ui (static SPA) |
| Marketing site | Astro (separate static build; SEO lives here) |
| Frontend hosting | Cloudflare Pages → S3+CloudFront on AWS later (same bundle) |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2 async + Alembic + Pydantic v2 |
| FE↔BE types | OpenAPI → generated TS client (`openapi-typescript` + `openapi-fetch`); drift fails CI |
| Database | Supabase Postgres (pooler in transaction mode: asyncpg `statement_cache_size=0`, no session state) |
| Vector search | pgvector + HNSW, same Postgres |
| Object storage | Supabase Storage now → S3 later, behind one adapter (both S3-API) |
| Auth | Supabase Auth + own `workspace`/`membership`/role tables |
| Job queue | Postgres `FOR UPDATE SKIP LOCKED` job table |
| Cache / rate limit | Upstash Redis (never the durable queue) |
| Server → browser | SSE (job progress, live transcript, streamed criteria) |
| Voice | Azure Speech Voice Live (GPT Realtime), browser↔provider direct; backend mints ephemeral tokens (D21). Central India region — a US region measured ~5 s vs ~2 s |
| Scoring / reports LLM | Claude Opus 5 (`claude-opus-5`) via official `anthropic` Python SDK |
| High-volume LLM | Claude Haiku 4.5 (`claude-haiku-4-5`) — tagging, drills, metadata |
| Transcription (M3) | Managed STT with diarization behind a `Transcriber` protocol |
| Backend hosting | Fly.io (one image, two apps) — try Oracle Cloud Always Free first |
| Email / analytics / errors | Resend / PostHog / Sentry |
| CI | GitHub Actions (public repo — see D18) |
| Observability | OpenTelemetry from week 1 → Sentry / Grafana Cloud free tier |

## 2. AI providers & models (D19)

| Role | Provider / model | Why |
|---|---|---|
| Live voice buyer | **Azure Speech Voice Live**, generative model `GPT Realtime` (speech-to-speech). Model and voice IDs held in `adapters/llm/models.py` | Anthropic has **no realtime speech-to-speech API** — a Claude key cannot power the voice layer. OpenAI Realtime direct could not be provisioned; Azure serves the same model and keeps D8's speech-to-speech design intact (D21). Measured ~2 s turn, barge-in working |
| Scoring & reports | `claude-opus-5` — $5/M input, $25/M output tokens | Structured outputs (`output_config.format` / `messages.parse()`) give schema-guaranteed rubric JSON; adaptive thinking; prompt caching for the static rubric+scenario prefix. ~6k in + 2k out per report ≈ **$0.08/session** — negligible vs voice minutes |
| High-volume tasks | `claude-haiku-4-5` — $1/M in, $5/M out | Tagging, drill selection, metadata extraction |
| Disputed-score adjudication (only if measured need) | `claude-fable-5` — $10/M in, $50/M out | D9: add a frontier tier only when evals show Opus 5 disagreement clusters; 2× Opus price buys headroom scoring doesn't normally need |
| Transcription (M3) | Deepgram or AssemblyAI (verify current pricing) | Diarization + word timestamps; replaceable behind `Transcriber` |

Rules: all model IDs and prices live **only** in `adapters/llm/models.py` · Anthropic calls use
the official `anthropic` SDK (never raw HTTP, never OpenAI-compatible shims) · voice-provider calls
only inside `adapters/voice/`, behind the `VoiceProvider` protocol · persona instructions come from
Postgres per session, never from the provider's own agent config (D21) · keys are server-side env
vars, never in the browser; the browser gets short-lived ephemeral tokens minted by `api`.

## 3. Module map

| Module | Owns |
|---|---|
| `identity` | workspace, membership, roles, invites |
| `catalog` | persona, scenario (+ applicable-criteria set), rubric & prompt versions (immutable) |
| `practice` | session lifecycle, ephemeral token minting, live transcript ingest |
| `review` | upload + Zoom ingest, transcription orchestration (M3) |
| `scoring` | rubric evaluation, evidence verification, provenance — crown jewel |
| `knowledge` | chunking, embedding, workspace-scoped retrieval |
| `insights` | aggregates, manager views, benchmarks |
| `platform` | queue, storage, email, metering, flags, audit |

**Boundary rule:** modules communicate through service functions and events only. No cross-module
SQL joins. This keeps later extraction (e.g. `scoring` as its own service) mechanical.

## 4. Voice session & the recording gap

Browser ↔ Azure Speech Voice Live directly; our server never proxies audio. Consequences:

- **Transcript:** Realtime data-channel transcript events are forwarded to `api` live (with turn
  + speaker boundaries — attribution verification depends on them). Durable server-side
  independent of audio upload → scoring starts the instant the call ends.
- **Audio (primary):** browser mixes mic + remote track via Web Audio
  (`AudioContext` + `MediaStreamDestination`), records with `MediaRecorder` (Opus ~24 kbps mono),
  uploads ~10 s chunks to signed URLs **during** the session.
- **Audio (fallback, if M0 Spike 2 fails on a target browser):** record mic track only;
  reconstruct buyer side from transcript. Playback degrades; scoring unaffected.

## 5. Latency budgets (hard numbers, measured per stage)

| Stage | Budget | How |
|---|---|---|
| Click → talking to buyer | < 5 s | Warm `api` (no serverless cold start), token mint < 300 ms, preflight done earlier, WebRTC handshake ~1–2 s |
| Voice turn (rep stops → buyer speaks) | ~1–2 s p95 | Provider-side VAD; short persona instructions; **no tool calls in the hot path**; static prefix cached |
| Live transcript lag | < 500 ms | Data-channel events → SSE fan-out, no DB write on the display path |
| Call end → deterministic metrics | < 1 s | Pure computation on the already-durable transcript; no LLM |
| Call end → first criterion visible | < 8 s | Single Opus 5 structured call, criteria streamed over SSE as produced |
| Call end → full report | p95 < 30 s | Prompt-cache rubric prefix; split into 2 parallel calls before downgrading model |
| Upload → scored report (M3) | Budget owned by transcription; progress always visible via SSE | |

Every stage emits an OTel span; the p95s live on one dashboard from M1.

## 6. Multi-tenancy — enforced twice

1. **Application layer (primary):** every repository function requires `workspace_id`;
   `WorkspaceContext` resolves it from the JWT once per request.
2. **RLS (defense in depth):** non-superuser DB role; `SET LOCAL app.workspace_id = ...` per
   transaction (transaction-scoped → pooler-safe); policies read
   `current_setting('app.workspace_id', true)`. Never the service-role key for user-facing reads.

`test_tenancy.py` proves cross-workspace isolation for every table, in CI.

## 7. Scoring engine

- Scenario-scoped criteria; outcomes = 1–5 **or** `insufficient_evidence` (excluded from averages).
- Structured output against a strict JSON schema (Claude structured outputs) — never parse prose.
- Verification before persist: quote **exists** in transcript + quote is in the **right
  speaker's** turn. Either failure → retry with feedback, capped; then a visible degraded-report
  state. Never persist unverified evidence.
- Deterministic metrics computed in code anchor the LLM's judgments.
- Provenance on every score: `(rubric_version, prompt_version, model_id, metrics_version)`.
- Eval harness (M2): weighted kappa + MAE vs external labels against the inter-rater ceiling.

## 8. Job & request flow

Request: SPA → generated client → FastAPI router → `WorkspaceContext` → module service →
repository (with `workspace_id`). Jobs: enqueue in the same transaction as the triggering write →
worker claims `FOR UPDATE SKIP LOCKED` → `queued → running → succeeded | failed(retryable)` with
`attempts`, exponential `run_after`, `idempotency_key` → progress over SSE → failures are
user-visible states. Full call chains: `FLOW.md`.

## 9. AWS migration map (M5 — env-var exercise)

Cloudflare Pages → S3+CloudFront · Fly.io → ECS Fargate/App Runner (same image) · Supabase
Postgres → RDS via `pg_dump` (or keep) · Supabase Storage → S3 (adapter endpoint swap) · Supabase
Auth → keep, or Cognito/self-hosted GoTrue · Postgres queue → keep, or SQS · Upstash →
ElastiCache. No EKS without a documented trigger (D10).
