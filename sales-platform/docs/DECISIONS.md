# Decisions

Every settled decision, with why. Re-litigating one costs a week; the rationale is recorded so
that doesn't happen by accident. New decisions append here (via the Quiz Rule in CLAUDE.md).
Each entry: decision → why → revisit trigger.

## D1 — Modular monolith, two deploy units. Not microservices.
One codebase, one Docker image, `api` + `worker`, eight internal modules. Microservices buy
independent scaling/deploys — pre-PMF and solo you need neither, and you'd pay in network calls,
schema drift, distributed tracing, N pipelines, and a five-container local setup. The one real
split (request/response vs long jobs) exists because a 20-minute transcode must never share a
thread pool with a token mint. **Revisit:** a module's scaling profile measurably diverges (GPU
transcription) or a second engineer is blocked deploying.

## D2 — One stack: Python backend, TypeScript frontend. Not polyglot.
"Four languages" reads as resume-driven development in interviews; one coherent stack + hard
boundaries + real evals + honest cost accounting is the strong signal. OpenAPI-generated TS
client gives type safety across the boundary. **Revisit:** never for style; only for a measured
capability gap.

## D3 — Supabase as data plane only. No Edge Functions.
Postgres + pgvector + Storage + Auth on one free project; exit is `pg_dump`. Edge Functions are
Deno, hard to test, and a rewrite on the AWS move — all business logic stays in FastAPI. Known
caveats accepted: ~7-day idle pause (scheduled ping / Pro while demoing), 500 MB DB / 1 GB
storage, transaction pooler needs `statement_cache_size=0`.

## D4 — Vite + React SPA + Astro marketing. Not Next.js.
Product is ~100% behind login: SSR/RSC buys nothing and costs a server runtime, a rendering model
that fights a WebRTC/audio client, and Vercel-shaped deploys. Static bundle hosts on Cloudflare
Pages free today, S3+CloudFront later, zero code change. SEO lives on the Astro site.

## D5 — Postgres job queue (`FOR UPDATE SKIP LOCKED`). Not Temporal.
~150 explainable lines: state machine, `attempts`, `run_after`, `idempotency_key`. Transactional
with the data, survives restarts, zero extra infra. **Revisit:** real volume with
human-in-the-loop multi-step workflows.

## D6 — pgvector in the same Postgres. Not Pinecone.
Retrieval must be workspace-filtered *before* search — a SQL `WHERE`, vs a metadata-filter dance
in an external store — and one sync-and-drift failure mode disappears. Comfortable to six figures
of chunks.

## D7 — Supabase Auth + own workspace/role tables. Not Clerk.
Auth rows in the same Postgres → real FKs, no MAU cliff, same `pg_dump` exit. Workspace tables
are needed regardless, so Clerk's orgs save less than they appear. **Revisit window: M0 only** —
the one argument for Clerk is buying the invite/org-switcher UI.

## D8 — Realtime speech-to-speech over WebRTC, browser↔provider direct.
Backend mints ephemeral tokens only; API keys never reach the browser; server never proxies
audio. Lowest latency and most natural interruptions; cost is the recording gap (solved
browser-side, ARCHITECTURE.md §4) and per-minute price (metered from day one). Highest-risk
decision → de-risked by M0 Spikes 1–2. Thin `VoiceProvider` protocol keeps a composed
STT→LLM→TTS pipeline as a contained escape hatch. **Revisit:** per-minute cost hurts at real
usage. **Vendor settled by D21** — the trigger that actually fired was provider *availability*,
which this entry failed to anticipate. The architecture below is unchanged; the escape hatch
stays unbuilt.

## D9 — Two model tiers. Not four/five.
Mid-tier reasoning for scoring/reports; cheap model for volume tasks; frontier tier only for
disputed-score adjudication if evals show the need. The four-tier plan optimized an unmeasured
cost.

## D10 — No Kubernetes.
Fargate/App Runner is the AWS ceiling for a long time. Reopening requires a documented trigger
(sustained autoscaling need, multiple teams, infra specialization).

## D11 — Billing deferred to M4; Stripe (or MoR), not Razorpay.
Market is global SaaS teams paying USD; Razorpay is for INR billing to Indian customers — a
different business. Metering and plan limits come first, because limits are what billing bills.

## D12 — Greenfield in `sales-platform/`.
The sibling `demo/` Spring Boot scaffold is unrelated; nothing reusable; never touched.

## D13 — Evidence = two code checks + one measured metric.
Existence and speaker attribution are code-enforced with retry-then-degrade. Relevance (does the
quote actually support the claim?) is not code-checkable → sampled human-judged eval metric,
never claimed zero. Misattributing the buyer's words to the rep is the single most damaging
failure this product can produce, and it's ~50 lines to prevent.

## D14 — Gold set labeled by 2–3 external sales managers; inter-rater ceiling published.
A self-labeled gold set measures agreement with yourself. Sales scoring is subjective — humans
won't fully agree, so a raw model kappa is uninterpretable alone. "Model agrees with sales
managers about as well as they agree with each other" is the falsifiable, credible claim.
Recruiting starts in M0 — longest-lead item in the plan.

## D15 — Quadratic-weighted kappa + MAE for agreement.
Scores are ordinal; plain kappa treats 4-vs-5 like 1-vs-5.

## D16 — Full provenance on every score: `(rubric_version, prompt_version, model_id, metrics_version)`, immutable once referenced.
A score is a function of all four; freezing only the rubric lets a prompt tweak silently change
what a 72 means.

## D17 — Scenario-scoped criteria + first-class `insufficient_evidence` outcome.
A 3-minute cold call has no positioning content; forcing all 7 criteria produces confident scores
over absent evidence — the exact trust failure the evidence check exists to prevent — and poisons
evals (humans mark N/A, model invents a score). `insufficient_evidence` is excluded from
averages and never styled as failure.

## D18 — CI/CD stays on GitHub Actions, repo goes public. Not GitLab.
GitHub Actions is free with **unlimited minutes for public repos** (private: ~2,000 min/month);
GitLab's free tier is ~400 compute minutes/month — migrating "for free CI" moves to a smaller
free tier (verify current limits, but the direction is clear). A public repo is also portfolio
evidence for the hiring goal. Whatever currently "doesn't work" in Actions is a config/limits bug
to diagnose (record the actual error in MEMORY.md), not a platform verdict. Public-repo
discipline: no secrets in git, no real-name transcripts, secrets via Actions secrets.
**Revisit:** a genuine platform blocker documented after diagnosis.

## D19 — Provider split: OpenAI for voice, Claude for scoring.
Anthropic has **no realtime speech-to-speech API**, so the live buyer runs on OpenAI Realtime
(exact model ID verified against live OpenAI docs at implementation, stored only in
`adapters/llm/models.py`). Scoring/reports run on **Claude Opus 5** (`claude-opus-5`, $5/$25 per
MTok): structured outputs give schema-guaranteed rubric JSON, prompt caching fits the static
rubric prefix, and a report costs ≈ $0.08 — negligible vs voice minutes. Volume tasks run on
**Claude Haiku 4.5** (`claude-haiku-4-5`, $1/$5). `claude-fable-5` ($10/$50) reserved as the
optional adjudication tier per D9. Two API keys required (OpenAI + Anthropic); both server-side
only. Note: a Claude Code subscription is not an API key — product API access is provisioned
separately in the Anthropic Console. **Revisit:** Anthropic ships a realtime voice API, or voice
cost forces the composed-pipeline escape hatch in D8. **Voice vendor superseded by D21** — still
GPT Realtime, now reached through Azure. The provider *split* (OpenAI family for voice, Claude for
scoring) is unchanged.

## D20 — Docs split into per-concern files under `docs/`, indexed by CLAUDE.md.
Replaces the single master document. PRD / ARCHITECTURE / RULES / PHASES / DESIGN / DECISIONS /
FLOW / MEMORY / V2-ROADMAP, each with an owner-doc rule ("if it's not in these files, it's not
decided"). FLOW.md additionally institutionalizes the staff-engineer onboarding pass so fresh
sessions verify the map instead of re-deriving it.

## D21 — Voice runs on Azure Speech Voice Live (GPT Realtime), not OpenAI direct.
D8 listed only cost as its escape-hatch trigger and assumed the provider would stay obtainable.
OpenAI Realtime API access could not be provisioned at all — a harder blocker than price. Azure
Speech Voice Live serves **the same GPT Realtime model** with speech-to-speech intact, so D8's
architecture survives whole: browser↔provider direct, backend mints a short-lived credential,
server never proxies audio. The composed STT→LLM→TTS pipeline stays unbuilt, and with it the
turn-taking and barge-in work that pipeline would have forced us to own.

Measured in the Foundry playground before committing: **~2 s response, barge-in cuts the buyer off
mid-sentence, persona held under a direct "are you an AI?" probe.** The same config in a US region
measured ~5 s — **region is load-bearing, not incidental**; the resource lives in Central India
next to the `ap-south-1` Supabase project.

Consequences: one voice provider, not two (an OpenAI implementation we cannot obtain would rot
untested), and `OPENAI_API_KEY` leaves the required set. Persona instructions live in Postgres and
ship per session, never in the Azure agent config — D16 needs `prompt_version` in the provenance
tuple, and a prompt living in a vendor console cannot be versioned, reviewed, or tested.
**Revisit:** turn latency regresses past 2 s p95 measured from a real client rather than the
playground, or OpenAI Realtime becomes obtainable and measurably faster.

## D22 - Execute migration statements individually with asyncpg.
Approved by the user on 2026-10-16 after reproducing CI's migration failure. SQLAlchemy's
asyncpg dialect prepares each execution and rejects multiple top-level SQL commands in one
call. Split existing migration batches into individual executions, preserving SQL, order,
revision IDs, RLS policies, and final schema. Function bodies remain single SQL statements.
Validate upgrade/downgrade/upgrade on a separate local database, schema drift, and real
unprivileged-role integration tests. Do not downgrade hosted data as a verification step.
`ALEMBIC_DATABASE_URL` optionally selects the direct/session connection for migrations;
`DATABASE_URL` remains the runtime transaction pooler. Preserve URL encoding of credentials
and escape percent signs for Alembic's ConfigParser; never log credential-bearing URLs.

## D23 - The signalling WebSocket is the call's lifeline; the browser owns it.
Measured 2026-10-24 with `spikes/run_voice_spike.py` (three sessions, Playwright Chromium and
Edge 156): after `ws.close()` the RTCPeerConnection stays `connected`, the remote track stays
`live`, yet the server emits no further events or audio - 0 turns completed after the drop
in every run while rep audio kept playing. So `negotiate()` cannot be fire-and-forget: whoever
opens the socket must hold it for the whole roleplay. Holding one socket per live call inside
`api` would make the API stateful and break D1's two-unit shape, so the **browser owns the
WebSocket** and `api` stays stateless. Consequence for M1: the browser needs a short-lived,
non-API-key credential for Azure Voice Live (Entra/issued token minted by `api`, the D8
"ephemeral token"); verifying that credential path is the first M1 task. **Fallback** if no
browser-safe credential exists: `api` holds the socket with sticky sessions, recorded as a
D1 amendment. **Revisit:** Azure documents the socket as closable without ending the call.

## D24 - Safari verification deferred; audio truth accepted on Chromium and Edge.
Spike 2 required Chrome and Safari. No Apple device is available to this solo build, and
the automated spike now proves the mixed mic+buyer recording on Playwright Chromium and
Microsoft Edge (both voices measured: RMS 0.07-0.10 against a 0.01-0.02 quiet floor, Opus/WebM,
`decodeAudioData` clean). M0 closes on that evidence; Safari (mp4 recorder path, autoplay
rules) becomes an M1 exit gate the first time a Mac or iPhone is at hand. The mic-only
fallback in ARCHITECTURE §4 stays documented and unbuilt. **Revisit:** a design partner on
Safari, or the first Safari run failing.

## D25 - Realtime usage is metered in provider token buckets, not seconds.
`response.done.usage` reports text/audio input (plus cached) and text/audio output tokens, and
that is what the provider bills. The ledger now records those six buckets with rates in
micro-USD per 1M tokens (`REALTIME_*_MICROUSD_PER_1M`); the per-minute seconds path remains
only for clients that cannot see usage, and any used bucket without a rate still flags
`rate_missing`. Measured 2026-10-24: a 170 s Priya roleplay (20 responses) cost **$0.142 =
$0.050 per talking minute** at gpt-realtime list prices, written to hosted `usage_events`
through API -> queue -> worker and read back by `/usage/summary` with the identical figure.
Session caps and trial limits can now be set from a number, not a guess. **Revisit:** Azure
publishes different Voice Live rates than the OpenAI list prices used here.

## D26 - Two runtime database roles; admin traffic uses the IPv4 session pooler.
The hosted `postgres` credential has BYPASSRLS, which silently disabled the second tenancy
boundary. `scripts/provision_runtime_roles.py` creates `hypersale_app` (LOGIN, NOBYPASSRLS,
DML only, no `alembic_version`) for the API and `hypersale_worker` (BYPASSRLS) used solely by
`system_session` for queue dispatch, writes both URLs to the ignored `.env`, and verifies the
app role sees zero rows without a tenant GUC. Migrations stay on `postgres`. The direct host
`db.<ref>.supabase.co` is IPv6-only and unreachable from the development network, so Alembic
and admin scripts use the Supavisor session pooler (port 5432); runtime keeps the transaction
pooler (6543). **Revisit:** Supabase offers an IPv4 add-on or the network gains IPv6.

## D27 - Scoring may reach Claude through an Anthropic-compatible gateway, never a shim.
The only available scoring credential is an Agent Router token. The gateway rejects raw HTTP
("unauthorized client") but accepts the official `anthropic` SDK with `base_url`, which is
exactly what D19 permits: the SDK is unchanged, `ANTHROPIC_BASE_URL` and
`ANTHROPIC_AUTH_TOKEN` are configuration, and model IDs stay in `adapters/llm/models.py`.
Spoofing another client's identity to satisfy the gateway is out of bounds. Status on
2026-10-24: the token permits only `claude-opus-5-5`, for which the gateway has no upstream
channel (503), so Spike 3 stays open until the token gains `claude-opus-5` or a direct key
or OpenRouter credential arrives. **Revisit:** when a model answers, re-run
`spikes/run_scoring_spike.py` and record its cost beside D19's $0.08 estimate.
