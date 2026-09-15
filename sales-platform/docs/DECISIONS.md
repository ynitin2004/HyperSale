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
