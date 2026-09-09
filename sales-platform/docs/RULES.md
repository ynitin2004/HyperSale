# Engineering Rules

Changing a rule requires a `DECISIONS.md` entry. Claude sessions: the Quiz Rule in `CLAUDE.md`
applies before any major change.

## 1. Prohibitions (hard)

- No microservices; no per-service tech stacks. Two deploy units, one image (D1, D2).
- No cross-module table access or cross-module SQL joins (module map in ARCHITECTURE.md §3).
- No hand-written duplicated API types — only the generated TS client; drift fails CI.
- No provider SDK usage outside `adapters/` (Anthropic SDK, OpenAI, storage, STT, email — all).
- No model IDs or prices anywhere except `adapters/llm/models.py`.
- No Supabase service-role key for user-facing reads.
- No business logic in Supabase Edge Functions.
- No Kubernetes before a documented trigger (D10).
- **No score persisted with unverified evidence** (existence + speaker attribution both pass, or
  the report is marked degraded).
- **No score persisted without full provenance** `(rubric_version, prompt_version, model_id,
  metrics_version)`.
- No API keys in the browser — the client receives only short-lived ephemeral Realtime tokens.
- No `docs/` drift: a PR that changes an execution path without updating `FLOW.md` is incomplete.

## 2. Reliability contracts

- Uniform error contract: typed error codes + correlation ID on every response.
- Idempotency keys on all mutating jobs; exponential backoff; at-least-once + dedupe.
- Structured JSON logs with correlation IDs; OTel traces from week 1; every latency-budget stage
  (ARCHITECTURE.md §5) emits a span.
- Job failures are user-visible states, never silent. Feature flags for anything user-visible
  pre-GA; commercial surface ships dark.
- Audio path instrumentation: every audio state transition (permission, device change, connection
  state, recorder state, upload chunk result) is a Sentry breadcrumb.

## 3. AI boundaries

- Strict versioned JSON schemas for every model output; rubric **and prompt** versions immutable
  once referenced.
- Anthropic calls: official `anthropic` Python SDK, `claude-opus-5` for scoring/reports with
  structured outputs and adaptive thinking; `claude-haiku-4-5` for high-volume tasks. Prompt
  caching on the static rubric+scenario prefix (stable content first; verify with
  `usage.cache_read_input_tokens` > 0).
- Evidence: existence + attribution verified in code; relevance measured by sampled human
  judgment, never claimed zero.
- Human-review path exists for disputed scores. **No AI decision directly controls billing or
  employee certification** — scores inform humans.
- Per-workspace metering (`usage_event`) on every AI call: tokens, audio minutes, computed cost.
- Session caps enforced server-side (voice minutes are the dominant cost).

## 4. Testing gates (details in PHASES.md; commands in the verification table)

- Unit: rubric math (incl. `insufficient_evidence` exclusion), both evidence negative cases
  (fabricated quote AND wrong-speaker quote rejected), job state machine, retention windows.
- Integration: `test_tenancy.py` on every table; role-permission tests.
- E2E: Playwright against a **stubbed voice provider** (no live API cost in CI); one real-provider
  smoke before any demo and weekly (stub-drift guard).
- AI evals: run in CI on every prompt/model change; regression beyond threshold fails the build.

## 5. CI/CD (D18)

- GitHub Actions on a **public** repo (unlimited free minutes for public repos; a public repo is
  also portfolio evidence). Do not migrate to GitLab for cost — its free tier has far fewer
  compute minutes (~400/month; verify current) than a public GitHub repo's unlimited.
- Secrets via GitHub Actions secrets; never in the repo. Public repo means: no credentials, no
  customer data, no gold-set transcripts with real names in git.
- Pipeline: lint + typecheck → unit → integration (throwaway Postgres service container) →
  client-codegen drift check → build image → (on prompt/model change) fast eval subset.
- A failing pipeline is fixed, not bypassed. If Actions itself misbehaves, diagnose the actual
  error before considering any migration (record in MEMORY.md).

## 6. Git & workflow

- Small PRs; `main` always deployable; migrations forward-only.
- Schema changes only via Alembic files in-repo — never applied directly through Supabase MCP or
  the dashboard (MCP is for inspection/diagnostics; see CLAUDE.md).
- Every meaningful session ends by updating `docs/MEMORY.md`.
