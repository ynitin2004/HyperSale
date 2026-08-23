# HyperSale — Project Memory

Durable, graph-derived memory of this repository. Read this first in a new session, then
[MASTER_PRODUCT.md](MASTER_PRODUCT.md) for product doctrine and [README.md](README.md) for how to run things.

Built by `/graphify` from the knowledge graph in [graphify-out/](graphify-out/) on 2026-08-24.
Source of every claim below: [graphify-out/GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md) and `graphify-out/graph.json`.

---

## Corpus at a glance

| | |
|---|---|
| Files | 71 (63 code · 8 documents) — ~11,926 words |
| Graph | 529 nodes · 994 edges · 42 communities |
| Provenance | 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS |
| Inferred edges | 72, average confidence 0.91 |
| Import cycles | none |
| Isolated nodes | 80 (mostly `package.json` / `tsconfig.json` leaf keys — noise, not gaps) |

The graph's own verdict, printed by graphify: *"Corpus is ~11,926 words — fits in a single
context window. You may not need a graph."* True today. The value here is not compression,
it is the **rationale layer** — the `rationale_for` edges that bind each decision to the code
it explains, so the *why* survives even when this file does not.

---

## The seven decisions that explain the code

Every one is a place where the obvious implementation is wrong. These are `rationale_for`
edges in the graph, anchored to real symbols.

| Decision | Anchored to | Why it exists |
|---|---|---|
| **RLS was inert as first written** | [20260824_0002…upgrade()](services/backend/alembic/versions/20260824_0002_queue_and_rls_hardening.py) | Policies had no `WITH CHECK`, so a session pinned to one workspace could still *write* into another; and without `FORCE`, the table owner bypassed every policy. Postgres still exempts superusers — the app must connect as an unprivileged role or the second boundary is silently off. |
| **Membership lookup cannot be workspace-scoped** | [identity_session()](services/backend/app/db/session.py) · [resolve_membership()](services/backend/app/modules/identity/service.py) | Resolving *which* workspace a caller may use requires reading `memberships` before a workspace is known. The policy therefore also admits a caller's own rows via an `app.user_id` GUC. |
| **The dispatcher is the only cross-tenant component** | [system_session()](services/backend/app/db/session.py) · [Worker.run_once()](services/backend/app/workers/main.py) | It sets no GUC and so needs a `BYPASSRLS` role. Handlers always run under `tenant_session`, so a handler cannot reach another tenant even by mistake. |
| **`SET LOCAL` cannot take bind parameters** | [_set_guc()](services/backend/app/db/session.py) | The original tenant session would have failed against a real database. GUCs now go through `set_config(..., true)`, which is transaction-local and safe under Supavisor pooling. |
| **Migrations could not run at all** | [run_migrations_online()](services/backend/alembic/env.py) | `env.py` built a sync engine, which silently required psycopg2 — not a dependency. It now runs async over the same asyncpg URL as the app. |
| **Realtime identity must come from the token** | [create_realtime_session()](services/backend/app/modules/practice/api.py) | The endpoint took `user_id` from the request body, so any unauthenticated caller could mint provider credentials against another identity. |
| **Unmeasured cost is not zero cost** | [realtime_audio_cost()](services/backend/app/modules/platform/usage.py) · [Settings](services/backend/app/config.py) | Rates are configuration defaulting to zero, and a zero rate applied to real audio is persisted as `rate_missing`, so summaries report a floor and never a false free. |

---

## Load-bearing nodes

The graph's most connected symbols — change these and the blast radius is wide.

| Node | Edges | Where |
|---|---|---|
| `get_settings()` | 28 | [app/config.py](services/backend/app/config.py) |
| `AuthError` | 22 | [app/errors.py](services/backend/app/errors.py) |
| `Settings` | 20 | [app/config.py](services/backend/app/config.py) |
| `AppError` | 20 | [app/errors.py](services/backend/app/errors.py) |
| `TokenVerifier` | 20 | [identity/tokens.py](services/backend/app/modules/identity/tokens.py) |
| `tenant_session()` | 17 | [db/session.py](services/backend/app/db/session.py) |
| `ClaimedJob` | 17 | [platform/queue.py](services/backend/app/modules/platform/queue.py) |
| `resolve_membership()` | 16 | [identity/service.py](services/backend/app/modules/identity/service.py) |
| `Worker` | 16 | [workers/main.py](services/backend/app/workers/main.py) |

`get_settings()` and `tenant_session()` are the two highest-betweenness bridges (0.119 and
0.044). Both are cross-community chokepoints: configuration reaches every module, and the
tenant boundary reaches every module that touches data. Treat edits to either as architectural.

---

## Structural map

42 communities. The 20 that carry real weight:

**Backend core** — Tenancy Doctrine And Sessions (42) · Durable Job Queue (49) · Identity And
Role Resolution (41) · Worker Dispatch And Handlers (33) · Token Verification And Errors (28) ·
App Configuration And Telemetry (48) · Request Correlation And Errors (13)

**Data and delivery** — Migrations And Schema Gates (30) · RLS Hardening Migration (4) ·
M0 Foundation Migration (3) · Single Image Process Roles (4) · Generated API Client (4)

**Product surface** — Realtime Session Minting (16) · Realtime Cost Metering (9) ·
Web SPA Shell (9) · Marketing Landing Page (1)

**Doctrine** — Evidence Scoring Doctrine (4) · M1 Deterministic Metrics (2) · M2 Rater Evaluation (2)

**Tests** — Error Envelope Tests (7) · Health Endpoint Tests (5), plus test nodes distributed
into the community of the code they cover, which is the healthy shape.

Cohesion is highest in the small, single-purpose communities (Health Endpoint Tests 0.53,
Evidence Scoring Doctrine 0.50) and lowest in the broad ones (App Configuration 0.06). That
is expected: configuration is *supposed* to be diffuse.

---

## Cross-cutting patterns the graph surfaced

Three hyperedges — groups whose relationship is not captured by any pair of edges:

1. **Workspace Tenancy Boundary** (0.95, EXTRACTED) — `TokenVerifier.verify` → `resolve_membership`
   → `current_principal` → `tenant_session` → the RLS migration. Five components, one guarantee.
   No single pairwise edge shows that the *whole chain* is the boundary.
2. **Durable Job Lifecycle** (0.95, EXTRACTED) — `enqueue` · `claim` · `mark_succeeded` ·
   `mark_failed` · `requeue_stalled` · `Worker.run_once`.
3. **Fail-Closed Defaults** (0.70, INFERRED) — `TokenVerifier.verify` · `realtime_audio_cost` ·
   `system_session`. Unrelated in code; identical in principle: **an absent value must never be
   read as a permissive default.** Unconfigured auth refuses. An unmeasured rate flags itself.
   An unpinned session returns nothing. This is the repo's strongest unwritten convention —
   preserve it in new code.

Five `semantically_similar_to` edges connect things nothing links structurally:

- `enqueue()` ↔ `record_usage()` (0.85) — same insert-or-return-existing shape on a natural
  key, in two modules, with no call between them. Change one idempotency strategy, revisit both.
- `TokenVerifier.verify` ↔ `resolve_membership()` (0.72) — both convert untrusted input into a
  trusted assertion and fail closed.
- `requeue_stalled()` ↔ `JwksCache.get()` (0.63) — both recover from staleness with one
  *bounded* refresh (lease expiry, key rotation) rather than unbounded retry.
- `Why Unmeasured Cost Is Not Zero Cost` ↔ `TokenVerifier.verify` (0.66) — the decision itself
  echoes the auth gate: an absent rate and an absent key are both refusals, not defaults.
- `heartbeat()` ↔ `tenant_session()` (0.60) — both scope a mutation to an owner so a peer
  cannot act on the same row.

---

## Audit — what is known versus what is claimed

**Verified by running it:** ruff clean; 39 unit tests pass; migrations render offline;
`apps/web` and `apps/marketing` both build; the OpenAPI document generates with 9 routes.

**Written but never executed here** — no Docker and no Postgres on this machine:
13 integration tests (tenant isolation, queue semantics), the image build, the migration
up/down round-trip, and `alembic check`. CI runs all four; the first push is their first run.
`alembic check` is the likeliest to need a tweak.

**Graph honesty:** 93% of edges are EXTRACTED (structural or explicit in a document). The 7%
INFERRED carry an average confidence of 0.91 and are individually scored. The `Fail-Closed
Defaults` hyperedge and the five `semantically_similar_to` edges are *model-reasoned
observations*, not facts in the source — the strongest claims here are also the least verified,
which is exactly the trade the audit trail exists to make visible.

---

## Open risks

- **Voice cost is unmeasured**, so every cost figure currently carries `rate_missing`. Until a
  real session sets the `REALTIME_AUDIO_*` rates, totals are a floor, not a number.
- **No rate limit on credential minting.** `POST /practice/realtime/session` is authenticated
  now, but a logged-in user can still burn provider spend. Wants Upstash Redis.
- **Cross-browser remote-track capture untested** (Chrome and Safari).
- **Raters not recruited**; Supabase credentials pending. Both block M2 and M0 respectively.

---

## Regenerating this memory

```bash
/graphify .                 # rebuild graph, communities, and GRAPH_REPORT.md
/graphify . --update        # incremental: re-extract only changed files
/graphify query "how does tenancy work?"
```

`graphify-out/graph.json` is the persistent artifact — it survives sessions, so an agent can
query relationships without re-reading the codebase. `graphify-out/graph.html` is the
interactive view. **Neither is tracked in git** (~1.1MB combined): a fresh clone has this file
and `GRAPH_REPORT.md` but must run `/graphify .` once to rebuild the queryable graph.

**Provenance:** structural extraction is deterministic AST parsing (486 nodes, 1202 edges).
The semantic layer (43 nodes, 60 edges, 3 hyperedges over the 8 document files) was extracted
inline rather than by parallel subagents, because the doc corpus is small; the reported token
cost of 0 reflects that, not a free run. Every semantic edge endpoint was validated against
the AST node set before merge — zero dangling edges.
