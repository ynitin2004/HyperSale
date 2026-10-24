# MEMORY - Living State

Read this first; update last each session. Current phase: **M0 closed 2026-10-24; M1 cleared.**
Application code lives at repository root; sales-platform/ owns product docs.

## Latest authoritative checkpoint - 2026-10-24

User authorized the full build-out ("full control", Docker + Supabase, push to both remotes).
Quiz answers: scoring via gateway, Safari deferred (D24), ~$5 Azure spend, hosted role
provisioning + pushes. The user pasted an Agent Router key into chat; it is in `.env` as
`AGENTROUTER_API_KEY` / `ANTHROPIC_AUTH_TOKEN` and should be rotated.

### Closed this session (evidence in PHASES.md checkpoint and docs/evidence/)

- Cost truth: automated 170 s Priya call, $0.142 = **$0.050/min**; ledgered through
  API -> queue -> worker on hosted DB (141,823 microusd), summary endpoint agrees (D25).
- Audio truth on Chromium + Edge (both voices measured); control channel answered: WS close
  ends the session while WebRTC stays up -> browser must hold the WS (D23).
- Latency on a real client: transcript mean 203 ms, audible mean 758 ms / p95 1,087 ms.
- Restricted roles `hypersale_app` / `hypersale_worker` provisioned and verified (D26);
  real Supabase login -> whoami 200 / 401; stale publishable key corrected.
- `docker compose up --build` gives db+migrate+api+worker (needed `sqlalchemy[asyncio]`).
- 42 unit + 13 integration tests, Ruff, web builds green locally. Docs: D23-D27, FLOW
  verified chains, ARCHITECTURE measurements, WALKTHROUGH.md, CLAUDE.md index rows.

### Still open

1. Scoring Spike 3: gateway 403 (`claude-opus-5`) / 503 no channel (`claude-opus-5-5`).
   `spikes/run_scoring_spike.py` is ready; needs model enablement or another credential (D27).
2. External raters not recruited (gates M2). User action.
3. Safari run deferred to M1 exit (D24). Sentry/OTel exporters unverified (no accounts).
4. Hosted CI: GitHub run #7 at `0b5b923` green (backend/web/image) after run #6 failed one
   RLS test. GitLab pipeline console unread: git OAuth token lacks `read_api`; ask the
   user for a `GITLAB_TOKEN` (read_api) in `.env` or a pasted console. `gh` CLI absent.

### Environment facts that bit

- Supabase direct host is IPv6-only here; admin/Alembic use the session pooler (5432).
- `pydantic-settings` reads `.env` from cwd: run scripts from the repo root, export
  `ALEMBIC_DATABASE_URL` for Alembic in `services/backend`.
- Agent Router rejects raw HTTP as "unauthorized client" but accepts the official SDK.
- No browser-control tools in this environment; Playwright (Chromium + Edge channel) with
  SAPI TTS as a fake mic is the working substitute. Chrome itself is not installed.

## Next actions

- Archive the GitLab pipeline console once a read_api token or paste is available.
- Start M1: browser-safe Azure Voice Live credential minted by `api` (D23), Azure
  `VoiceProvider` adapter, session flow, scoring module on `adapters/llm/client.py`.
- User: fix the scoring credential (enable `claude-opus-5` on the Agent Router token, or
  supply OpenRouter/direct key), rotate the pasted key, start rater recruitment.

## Previous checkpoint - 2026-10-16

User authorized .env database/password repair and migrations after the issue report.
No Git push or deployment is authorized. Prior report-before-repair preference still applies
outside this approved scope. No repeated quiz is needed for these explicitly approved fixes.

### Completed and verified

- Corrected database password and URL encoding in ignored .env, without printing it.
  Runtime DATABASE_URL uses verified Supabase transaction pooler (6543); optional
  ALEMBIC_DATABASE_URL uses verified direct connection (5432). Do not log these URLs.
- Alembic now reads its dedicated URL (fallback to runtime URL), escaping percent signs
  for ConfigParser. Updated .env.example to document the setting.
- Split migration 0001/0002 batches into single top-level statements. SQL content/order,
  revision IDs and final schema preserved (normalized comparison against HEAD checked).
- Fixed test fixture URL serialization with hide_password=False for connection only.
  Runtime auth/tenancy policies unchanged.
- Fresh local DB hypersale_m0_verify_20261016: upgrade/downgrade/upgrade passes,
  alembic check clean, all 52 tests pass (39 unit + 13 integration), Ruff clean.
- After verifying hosted project initially had no M0 tables, applied user-authorized
  Alembic migrations to Supabase. Current revision 20260824_0002 (head); hosted
  alembic check clean. No hosted downgrade or integration-fixture mutations performed.
- Hosted workspaces/memberships/usage_events/jobs all have ENABLE + FORCE RLS.
- API TestClient with hosted runtime config: /health 200, /api/v1/ready 200,
  unauthenticated /api/v1/whoami 401. Authenticated product login remains unverified.
- Earlier working-tree pnpm CI version repair remains aligned in GitHub/GitLab.
  React + Astro builds passed in previous session. No commits/push this session.
- Root AGENTS.md, PHASES.md, FLOW.md, ARCHITECTURE.md and decision D22 updated.

### Outstanding gates and concrete findings

1. Hosted runtime credential currently has BYPASSRLS. It connects successfully, but a
   separate unprivileged runtime role is required before production tenancy acceptance.
   Local isolation tests do use an unprivileged role; do not claim hosted isolation from them.
2. D21 selects Azure Voice Live. Only protocol/model registry/persona/browser spike exist;
   practice/api.py still uses OpenAI direct. No Azure adapter implemented yet. Its lifecycle
   depends on real signalling-drop results. Paid/live voice checks not run this session.
3. Chrome file launch command succeeded. To fix file-link friction, started local-only
   static server scoped to spikes/ at http://127.0.0.1:8765/voice-live-webrtc.html,
   PID 30024; verified HTTP 200 and title. Later localhost Chrome launch was rejected by
   automatic approval review (blocked by policy); no alternate launch workaround attempted.
   User can click the URL manually. Browser-control tools are still absent.
4. User identified supplied key as Agent Router. Official Anthropic 401 was expected for
   a third-party credential; read gateway's documentation. GET /v1/models with bearer auth
   returned 401 on both agentrouter.org and documented co.agentrouter.org. No inference,
   gateway integration, model change or gateway credential storage. Need valid local key
   and exact account dashboard base URL before further configuration. Do not repeat keys.
5. Previous headless Chromium recording smoke captured both synthetic tones only. Still
   need real Chrome/Safari mic+buyer playback, signalling drop, p95 latency, timed usage/cost,
   scoring fixture cost, telemetry and external sales-manager rater recruitment.
6. Supabase MCP CLI was authenticated read-only. Tools are still not exposed here despite
   user reload. Real database work this session used asyncpg diagnostics and repo Alembic;
   do not imply MCP queries were performed. Do not request repeated OAuth login unnecessarily.
7. Latest observed hosted GitHub CI is historical failing run 35901907546 at a6edbbc.
   Migration and fixture causes now fixed locally, but hosted rerun requires authorized push.
   GitLab public API returned 404; its status remains unknown.
8. Phone remote pairing not verified; laptop/host must remain available. No cloud deployment.

## Next actions as of 2026-10-16 (superseded by the 2026-10-24 checkpoint above)

- User: open local spike URL, supply Azure key locally, allow microphone, speak, drop
  signalling and report whether buyer continues. Save recording and confirm both voices;
  capture latency/usage, repeat Safari. First live log received; playback and drop-test results remain unknown.
- Resolve Agent Router credential/base URL; it is not a direct Anthropic key. Keep model
  choice unchanged until verified (user named Opus 4.8; docs still name Opus 5).
- Propose restricted runtime DB role setup, then authenticated login and tenancy validation.
- Choose Azure adapter lifecycle after live evidence, complete cost and scoring spikes,
  then obtain push permission to verify hosted CI. M0 is not complete and M1 not cleared.

## Standing rules

Follow CLAUDE.md and owner docs. PHASES.md after each task; FLOW.md for execution changes;
DECISIONS.md for precedents; MEMORY.md last. Report issues before repairs outside authorized
scope. Never expose .env secrets, push Git remotes, deploy/publish, or mutate hosted data
without explicit permission. Current approved hosted migrations have been completed.
Keep GitHub and GitLab CI aligned. Do not touch unrelated sibling projects.

## History

- 2026-08-24: plan/docs scaffold and D13-D20, evidence/eval rules, session quiz.
- 2026-09-23: Claude voice harness committed at a6edbbc; live voice gates left open.
- 2026-10-24: morning read-only audit, then full M0 closure: automated voice spikes, cost
  truth ledgered on hosted DB, restricted roles, auth login, compose stack, D23-D27, push.
- 2026-10-16: history/source audit, unit/build/synthetic recording checks, read-only MCP
  OAuth setup; identified migration, fixture and connection bugs. User approved DB repairs
  and migrations; all local DB tests and hosted migrations/schema check now pass.

## User live voice log - 2026-10-16

- Signalling/WebRTC connection succeeded, remote track and data channel arrived, mixed
  Opus WebM recording started, 10 turns observed, saved recording reported as 1252 KB.
- Samples 134/138/120/187/139/147/117/133/161/148 ms: mean 142.4 ms. Existing harness
  measures speech_stopped to first transcript/text delta; do not claim audible latency
  or voice p95 acceptance from this metric. Report measurement limitation before changes.
- Log has normal disconnect and WS close at 03:05:51, after last turn at 03:05:48;
  no Drop signalling/KEEP TALKING marker. Adapter lifecycle still undecided.
- Ask user whether saved playback includes both voices and whether they explicitly
  dropped signalling while staying connected, then received further buyer answers.
  Browser/version, Safari, audible onset, timed provider usage/cost remain outstanding.
- PHASES.md updated with evidence; no implementation changed and no push/deployment.

## Latest gateway credential check - 2026-10-16

Replacement supplied credential (user calls model "opus 5-5") returned HTTP 401
from GET /v1/models on both co.agentrouter.org and agentrouter.org with bearer auth.
No secret recorded here or saved to .env, no inference, no model switch, no push.
Ask for exact API base URL and exact model ID from their dashboard, not more pasted keys.
Advise replacement of keys shared in chat and local .env entry. Voice evidence questions
remain pending; gateway clarification does not replace the M0 objective.

## Agent Router screenshot and precise rejection - 2026-10-16

User screenshot shows agentrouter.org/console/token, enabled token, and allowed model
label claude-opus-5-5. Do not claim API availability or underlying model provenance from UI.
Read precise GET /v1/models response: both Bearer and Anthropic x-api-key headers return
401 unauthorized_client_error with "unauthorized client detected". Earlier checks were
too narrow: HTTP status alone did not establish key invalidity. Provider-side client
restriction blocks this caller; ask provider for supported app clients/external API access
and correct endpoint. Do not spoof another client to bypass the restriction.
No paid inference or new model/provider configuration. No keys recorded here or persisted.
Phase tracker updated; original M0 voice tests and other gates still pending.
