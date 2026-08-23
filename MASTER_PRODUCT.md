# HyperSale — Master Product Document

**Version:** 1.1  
**Status:** Locked baseline  
**Owner:** Solo founder/builder

This is the single product-level source of truth. Read it first at the start of each session and update the living-memory section last.

## Mission

HyperSale is an AI sales-performance platform for English-speaking B2B SaaS teams. Reps practise cold calls and discovery against realistic AI buyers, then receive evidence-backed coaching. Every criticism must have a clickable, timestamped quote that exists in the transcript and is attributed to the correct speaker.

The strategic outcome is a YC-level engineering demonstration: convincing voice roleplay, deterministic metrics in under one second, a complete report at p95 under 30 seconds, measured agreement with external sales-manager raters, and honest cost per roleplay minute.

## Product direction and launch scope

The full direction includes live roleplay, recording review, scenario/persona/rubric catalog, manager assignments and insights, knowledge retrieval, integrations, billing, and enterprise controls.

M0–M2 ships only the differentiating loop: five curated scenarios, browser voice roleplay, durable transcripts, chunked recordings, scenario-scoped rubric scoring, evidence seeking, drills, workspace tenancy, metering, external-rater gold set, and manager review. CRM, dialers, SSO/SCIM, data residency, builder UI, billing, and broad integrations are deferred until demand proves them necessary.

## Non-negotiable scoring rules

- Each criterion outcome is `1..5` or `insufficient_evidence`; the latter is neutral and excluded from averages.
- Rubrics, prompts, metric implementations, and model IDs are immutable once referenced. Every persisted score carries all four versions.
- Evidence is verified in code before persistence: normalized quote existence and speaker attribution against transcript turns. Failure retries a bounded number of times, then produces an honest degraded report.
- Evidence relevance is a sampled human-evaluation metric, not a zero-hallucination claim.
- Deterministic metrics include talk/listen ratio, longest monologue, fillers, questions, interruptions, and dated next-step detection.
- Gold labels come from two or three external practising sales managers. Report quadratic-weighted kappa and MAE against the measured inter-rater ceiling.

## Locked architecture

Vite + React 19 SPA; Astro marketing site; Python 3.12/FastAPI; SQLAlchemy async; Alembic; Supabase for Postgres/Auth/Storage; pgvector; Postgres `SKIP LOCKED` queue; Upstash Redis only for ephemeral caching/rate limits; Cloudflare Pages; Fly.io API and worker from one image; OpenTelemetry, Sentry, PostHog; Stripe only after demand.

This is a modular monolith: one codebase, one Docker image, and two deploy units (`api`, `worker`). The owned modules are identity, catalog, practice, review, scoring, knowledge, insights, and platform. Modules communicate via service functions/events; no cross-module SQL joins. Every repository method requires `workspace_id`; database RLS is the second boundary.

Voice is browser-to-provider WebRTC with short-lived backend-authorized credentials. The standard provider API key stays server-side. Browser audio is mixed and recorded in chunks; transcript events are durable independently of audio. Providers are wrapped by adapters.

No microservices, Kubernetes/EKS, Next.js, NestJS, Temporal, Pinecone, Clerk, Razorpay, self-managed data stores, Supabase Edge Functions, or hand-written duplicate API types in the initial product. AWS migration targets ECS Fargate/App Runner before Kubernetes is ever reconsidered.

## Delivery gates

### M0 — skeleton and truth

Create this monorepo, protected API path, Supabase-ready schema, Docker image with API/worker entrypoints, CI, telemetry, and usage event table. Run a real three-minute voice session to capture usage/cost. Test local+remote audio recording on Chrome and Safari; use documented mic-only fallback if required.

### M1 — roleplay loop

Seed five scenarios. Deliver session start under five seconds, live transcripts, recordings, deterministic metrics under one second, evidence-backed report p95 under 30 seconds, and audio seeking from evidence.

### M2 — evaluation and manager loop

Recruit raters, create a 30+ transcript gold subset, CI-gate score regressions, and add assignments/team comparison.

### M3–M5

Add upload/transcription review through the same scoring path; then retention, metering limits, roles and optional billing; finally only perform AWS migration when justified. Integrations follow design-partner demand.

## Verification

Unit tests cover evidence negative cases, score math, provenance, jobs, and retention. Integration tests prove tenant isolation and roles. Playwright uses a deterministic voice stub. AI evaluations measure weighted kappa/MAE, inter-rater ceiling, fabricated/misattributed evidence, relevance sampling, insufficient-evidence rate, latency, and cost. A real provider smoke test happens before every demo.

## Living memory and decision log

**Current state:** M0 code is complete and unit-tested. The protected API path, workspace tenancy, durable `SKIP LOCKED` queue, usage metering, and telemetry all exist. What remains in M0 is not code: it is credentials and two measurement spikes.

**Active risks:** voice cost still unmeasured, so every cost figure is currently `rate_missing`; cross-browser remote-track capture untested; raters not recruited; Supabase project credentials pending; integration tests have never run against a real Postgres outside CI.

**Next actions:** provision Supabase and run `alembic upgrade head` against it; create the unprivileged application role and the `BYPASSRLS` worker role; run a three-minute voice session and set the measured `REALTIME_AUDIO_*` rates; test Chrome and Safari audio capture; record all results here.

**2026-08-24:** HyperSale root created. The master document was committed as the product baseline; no existing `demo/` files were changed.

**2026-08-24 (M0 build):** Decisions worth remembering, because each one is a place the obvious implementation is wrong.

- *RLS was inert as first written.* Policies had no `WITH CHECK`, so a session pinned to one workspace could still insert rows into another, and `FORCE` was missing, so the table owner bypassed the policies entirely. Both are fixed in `20260824_0002`. Postgres still exempts superusers, so the application must connect as an unprivileged role in every environment.
- *Membership lookup cannot be workspace-scoped.* Resolving which workspace a caller may use requires reading `memberships` before a workspace is known. The policy therefore also admits a caller's own rows via an `app.user_id` GUC, and `identity_session` sets only that one.
- *The queue dispatcher is the single cross-tenant component.* It runs under `system_session`, which sets no GUC and so needs a `BYPASSRLS` role. Handlers always run under `tenant_session`, so a handler cannot reach another tenant even by mistake.
- *`SET LOCAL` cannot take bind parameters.* The original tenant session would have failed against a real database; GUCs now go through `set_config(..., true)`.
- *Migrations could not run at all.* `alembic/env.py` built a sync engine, which silently required psycopg2, which is not a dependency. It now runs async through the same asyncpg URL as the app.
- *Realtime credential minting trusted a body field.* `POST /practice/realtime/session` took `user_id` from the request, so any caller could mint provider credentials against another identity, unauthenticated. Identity now comes from the verified token. Per-user rate limiting is still missing and is the remaining abuse risk on that endpoint.
- *Unmeasured cost is not zero cost.* Rates are configuration defaulting to zero, and a zero rate applied to real audio is persisted as `rate_missing` so summaries report a floor, never a false free.

