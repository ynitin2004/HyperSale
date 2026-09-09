# MEMORY — Living State

Read this first every session. Update it last, every session. If a fact isn't in `docs/`, it
isn't decided.

## 1. Current baseline (2026-08-24)

- **State:** Greenfield. Docs scaffold complete (`CLAUDE.md` + 9 files in `docs/`). No code yet.
  Sibling `demo/` Spring Boot project is unrelated — never touch.
- **Current milestone:** M0 — not started.
- **Locked:** modular monolith (2 deploy units) · Python/FastAPI + Vite/React · Supabase data
  plane · Postgres queue · OpenAI Realtime voice + Claude Opus 5 scoring + Haiku 4.5 volume
  (D19) · evidence verified for existence AND speaker attribution · externally-labeled gold set
  with published ceiling · GitHub Actions on a public repo (D18) · full list in DECISIONS.md.
- **Out of v1:** Next.js, NestJS, Temporal, Pinecone, Clerk, Razorpay, Kubernetes, GitLab.
  Deferred features: V2-ROADMAP.md.

## 2. Active risks (ranked)

1. **Voice cost unmeasured** — blocks pricing/caps. Resolves: M0 Spike 1.
2. **Remote-track audio capture unproven** (worst on Safari) — could invalidate recording
   design. Resolves: M0 Spike 2; fallback documented (ARCHITECTURE §4).
3. **External raters not recruited** — longest lead time; gates M2, which is the interview.
   Start outreach immediately.
4. **GitHub Actions failure undiagnosed** — user reports CI "not working"; actual error not yet
   captured. Decision D18 says diagnose, don't migrate. Needs: the failing run's error text.
5. **Auth decision window** (D7) closes end of M0 — Supabase Auth default vs Clerk.
6. **OpenAI Realtime model ID + pricing unverified** — verify against live docs before any code
   references it (only in `adapters/llm/models.py`).

## 3. Next actions

1. `git init` in `sales-platform/`, first commit of docs, public GitHub repo, minimal CI
   (lint placeholder) to confirm Actions works at all.
2. Capture the actual failing-CI error from the user's existing repo → diagnose (risk 4).
3. Monorepo skeleton + Dockerfile (two entrypoints) + docker compose.
4. Supabase project + Alembic baseline + pooler-safe asyncpg config.
5. M0 Spike 1 (cost truth) and Spike 2 (audio truth) — before product code.
6. M0 Spike 3 (Opus 5 structured-output scoring call against a fixture transcript).
7. Begin rater outreach (risk 3). Decide auth (risk 5).
8. Optional: connect Supabase MCP (read-only, project-scoped) for inspection.

## 4. Session log

| Date | What happened |
|---|---|
| 2026-08-24 | Plan v1.0 (user's master doc) reviewed; 7 corrections folded in as v1.1 (D13–D17). Docs split into per-concern files (D20). CI decision D18 (stay on GitHub, public repo). Provider split D19 (OpenAI Realtime voice — Anthropic has no realtime speech API; Claude Opus 5 scoring ≈ $0.08/report; Haiku 4.5 volume). Hyperbound gap analysis → V2-ROADMAP.md. Quiz Rule installed in CLAUDE.md. |

## 5. Quiz Rule reminder

Before any major change (definition in CLAUDE.md): quiz the user 3–5 questions — what it
affects, what breaks if wrong, rollback, cost — wait for answers, then implement, then record in
DECISIONS.md if precedent-setting and FLOW.md if it touches an execution path.
