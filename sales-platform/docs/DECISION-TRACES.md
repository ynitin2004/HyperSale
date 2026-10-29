# DECISION TRACES — why each decision was made, and the test that keeps it true

`DECISIONS.md` says *what* was decided. This file is the audit trail: for every decision, the
trace of evidence that led to it, and the **test that fails if the decision is broken**. A
decision with no guard is listed as such, so the gap is visible rather than assumed away.

How to run every guard: see `WALKTHROUGH.md` §2 (unit, integration, decision tests),
§4–5 (live spikes), §6 (browser E2E). Executable decision tests live in
`services/backend/tests/test_decisions.py` and run in CI on every push.

Legend — **Guard**: what fails if the decision is violated. **Verified**: last date the guard
ran green against this repo (CI, local, or live). ⚠ = no automated guard yet.

## Architecture and platform

| ID | Decision | Trace (why) | Guard | Verified |
|---|---|---|---|---|
| D1 | Modular monolith, two deploy units, one image | Solo build; extraction stays mechanical via module boundaries | CI `image` job: one image, `PROCESS_ROLE` api/worker/migrate, unknown role exits 64; `docker compose up --build` runs all roles | 2026-10-24 CI #7; compose 2026-10-24 |
| D2 | Python backend, TypeScript frontend | One language per tier | Build + lint jobs | 2026-10-29 |
| D3 | Supabase as data plane only; no Edge Functions | Business logic must be testable in-repo | ⚠ No `supabase/functions/` exists; not machine-checked | 2026-10-29 (manual) |
| D4 | Vite + React SPA, Astro marketing | No SSR need for an authenticated app | `pnpm -r build` in CI `web` job | 2026-10-29 local |
| D5 | Postgres queue with `FOR UPDATE SKIP LOCKED` | No broker to run; DB already owns truth | `tests/integration/test_queue_db.py` (claim, redelivery, backoff, stall, lease ownership) | 2026-10-29 local, 13+2 integration |
| D6 | pgvector in the same Postgres | Retrieval is M3+ | ⚠ Not built yet (knowledge module empty) | — |
| D7 | Supabase Auth + own workspace/role tables | Auth is commodity; tenancy is ours | `tests/test_tokens.py`, `test_identity.py`; live: Supabase password login → `/whoami` 200 / no token 401 (`scripts/seed_dev_user.py`, `scripts/live_smoke.py`) | 2026-10-29 live |
| D8 | Browser↔provider media direct; server never proxies audio; no keys in browser | Latency; key safety | `test_decisions.py::test_d8_no_provider_credential_reaches_the_browser`; `VoiceProvider` protocol carries only SDP + JSON | 2026-10-29 |
| D9 | Two model tiers | Don't optimise unmeasured cost | Model IDs centralised (`test_rules_1_model_ids_live_only_in_models_py`) | 2026-10-29 |
| D10 | No Kubernetes | No trigger | ⚠ Policy only | — |
| D11 | Billing deferred to M4 | Nobody has asked to pay | ⚠ Policy only | — |
| D12 | Greenfield in `sales-platform/` | Sibling `demo/` is unrelated | ⚠ Policy only | — |
| D18 | GitHub Actions on a public repo; GitLab is a mirrored fallback | Unlimited public minutes | Both CI files changed together in every CI commit (memory rule + review) | 2026-10-29 |
| D20 | Docs split per concern, indexed by CLAUDE.md | No product knowledge in chat only | ⚠ Review only | — |
| D22 | One SQL statement per migration execute | asyncpg rejects multi-statement prepares (CI run 35901907546 failed on it) | `test_decisions.py::test_d22_each_migration_execute_holds_one_statement`; CI up/down/up + `alembic check` | 2026-10-29 local + hosted check |
| D26 | Two runtime DB roles; admin via IPv4 session pooler | Hosted `postgres` had BYPASSRLS → RLS inert; direct host IPv6-only here | `scripts/provision_runtime_roles.py` self-verifies (app role sees 0 rows without GUC); integration tests run as an unprivileged role; hosted grant query (catalog INSERT denied to app role) | 2026-10-29 hosted (MCP query) |

## Scoring trust (the product's core claim)

| ID | Decision | Trace (why) | Guard | Verified |
|---|---|---|---|---|
| D13 | Evidence = existence + attribution in code; relevance measured | Misattributed buyer words are the most damaging failure | `tests/test_verify.py` (fabricated, misattributed, wrong turn, too short, normalisation); `test_scoring_run.py` (retry-with-feedback, cap, degrade); `/api/v1/evidence/integrity` re-verifies every persisted quote | 2026-10-29 live: 53/53 hosted quotes pass |
| D14 | Gold set labelled by 2–3 external sales managers | Self-labelling measures agreement with yourself | ⚠ Human action: raters not yet recruited — **blocks M2** | — |
| D15 | Quadratic-weighted kappa + MAE | Scores are ordinal | ⚠ M2 eval harness not built | — |
| D16 | Full provenance on every score, immutable | A score is a function of rubric, prompt, model, metrics | `test_decisions.py::test_d16_*`; integration asserts all four fields on a scored report; seed refuses to mutate an existing rubric version | 2026-10-29 |
| D17 | Scenario-scoped criteria + `insufficient_evidence` | Forcing all criteria invents scores over absent evidence | Integration: report criteria == scenario's applicable set; Spike 3 + live: out-of-scope criterion returned `insufficient_evidence`; UI renders it neutral (E2E) | 2026-10-29 |
| D19→D28 | Scoring model: Claude Opus 5 → `gpt-5.6-sol` via gateway, official Anthropic SDK | Every Claude model on the only credential: 503 "no channel"; gpt-5.6-sol answers | Spike 3 ×3 (D13 0/0 each); live product calls scored `ready` with 0 rejected quotes; model ID only in `models.py` | 2026-10-29 live |
| D27 | Gateway via official SDK only; never spoof a client | Gateway fingerprints clients | `test_decisions.py::test_d27_no_client_identity_is_spoofed` (no User-Agent / default_headers override in app code) | 2026-10-29 |

## Voice

| ID | Decision | Trace (why) | Guard | Verified |
|---|---|---|---|---|
| D21 | Azure Voice Live (GPT Realtime) instead of OpenAI direct | OpenAI Realtime unobtainable; same model on Azure | `scripts/live_smoke.py` real calls | 2026-10-29 live, 5 calls |
| D23 | Signalling socket is the call's lifeline | Drop test: PC stays `connected`, 0 turns after `ws.close()` (3 runs, 2 browsers) | `docs/evidence/voice-spike-2026-10-24/*.json`; re-runnable `spikes/run_voice_spike.py --drop-after N` | 2026-10-24 |
| D24 | Safari deferred; audio truth accepted on Chromium + Edge | No Apple device | Live smoke records + plays back mixed WebM on Edge 157 and Chromium; ⚠ Safari unverified — **M1 exit gate** | 2026-10-29 |
| D25 | Meter realtime in provider token buckets | Provider bills tokens, not seconds | `tests/test_usage.py` (bucket pricing, missing-rate flag); live: $0.128 for a 3-min call ledgered, `rate_missing=false` | 2026-10-29 live |
| D29 | api brokers the Voice Live socket (amends D1, D8) | No browser-safe Voice Live token exists; resource has no Azure OpenAI realtime surface (client_secrets → 404) | Integration `test_m1_loop.py` (connect once → 409 on second, server transcript, end → report); live: 38–42 server-captured turns per call | 2026-10-29 live |
| D30 | Global read-only catalog; content-hashed prompt versions | Product content shared in v1; prompts must be versioned | `tests/test_catalog_seed.py`; integration: catalog readable from any tenant; hosted: app role has SELECT, not INSERT, on catalog tables | 2026-10-29 hosted |
| D31 | Stub providers for CI/E2E; storage adapter for recordings | RULES §4: E2E without spend | Playwright `apps/web/e2e/roleplay.spec.ts` (4 tests) + CI `e2e` job; recording round-trip in integration | 2026-10-29 local |
| D32 | Transcript text server-authoritative; usage + timing from browser, bounded | Raw socket event counts showed no `response.done` / VAD events on the api socket | `test_voice_events.py::test_browser_reported_usage_is_capped_by_call_length`; `test_decisions.py::test_d29_*`; integration: start may move earlier only, text unchanged; live: data_channel usage row + seek to turn start | 2026-10-29 live |

## Open decisions and their triggers

- **Safari** (D24): run `scripts/live_smoke.py`-equivalent manually on a Mac/iPhone; if the
  mp4 recorder path fails, adopt the mic-only fallback (ARCHITECTURE §4) and record it.
- **Prompt caching** (RULES §3, waived in D28): the gateway reports no cache reads; re-check
  `cache_read_input_tokens` whenever the scoring provider changes.
- **Multi-instance api** (D29): the first time more than one api instance is needed, add sticky
  routing or move the socket broker into its own deploy unit — record as a D1 amendment.
