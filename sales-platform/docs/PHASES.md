# Delivery Phases

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
