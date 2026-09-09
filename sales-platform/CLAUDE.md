# Sales Platform — Claude Session Protocol

AI sales-performance platform: live voice roleplay against AI buyer personas + evidence-backed
call scoring. Solo build, optimized for a YC-level hiring demo. Greenfield — the sibling `demo/`
Spring Boot project is unrelated; never touch it.

## Read order (every session, before any work)

1. `docs/MEMORY.md` — current state, active risks, next actions. Always first.
2. The doc that owns the area you're touching (see index below).
3. `docs/FLOW.md` — before changing anything on an execution path.

Before ending a session: update `docs/MEMORY.md` (state, risks, decision-log rows). This is the
last action of every working session, not optional.

## Documentation index

| File | Owns | Update when |
|---|---|---|
| `docs/PRD.md` | What the product is, users, scope, success metrics | Scope or metric changes |
| `docs/ARCHITECTURE.md` | Stack, modules, flows, tenancy, voice, scoring, latency budgets, AWS map | Any structural change |
| `docs/RULES.md` | Engineering rules, prohibitions, AI boundaries, reliability contracts | Rule added/changed (needs a DECISIONS.md entry) |
| `docs/PHASES.md` | Delivery milestones M0–M5 with acceptance criteria | Milestone completed or re-scoped |
| `docs/DESIGN.md` | Design system, UX states, audio-reliability playbook, latency UX | Any user-facing surface work |
| `docs/DECISIONS.md` | Every decision (D1–D20+) with rationale — why, alternatives, revisit triggers | Every new decision, before implementing it |
| `docs/FLOW.md` | Entry points, execution order, what calls what, AI-decision-point registry | Every PR that adds/changes an execution path |
| `docs/MEMORY.md` | Living memory: baseline, risks, next actions, log | End of every session |
| `docs/V2-ROADMAP.md` | Hyperbound-parity gap list, triggers to build each | A design partner asks for something on it |

Rule: if a fact about the product is not in these files, it is not decided. No product knowledge
lives only in chat history.

## The Quiz Rule (mandatory before major changes)

Before implementing any **major change**, Claude must first quiz the user — 3 to 5 short
questions — and wait for answers before writing code. The quiz is for the user's understanding
(this is their codebase and their interview material), not a formality. Questions should cover:
what the change affects, what breaks if it's wrong, how to roll it back, and what it costs.

A change is **major** if it involves any of: a new dependency · a schema migration · a new or
changed API endpoint contract · anything in `adapters/` (provider/model change) · anything in
`modules/scoring/` · tenancy or auth logic · deleting or rewriting more than ~100 lines ·
spending money (new service, model tier change) · a deviation from ARCHITECTURE.md or RULES.md.

After the quiz, record the change in `docs/DECISIONS.md` if it sets a precedent, and update
`docs/FLOW.md` if it touches an execution path.

## Onboarding prompt (for a fresh session once code exists)

When a new session needs to rebuild context on the codebase, don't ask "analyze this codebase."
Use FLOW.md first; if it's stale or you need depth, run the onboarding pass defined at the top of
`docs/FLOW.md` and repair FLOW.md with what you learn.

## Supabase MCP (when connected)

- Use it for **inspection and diagnostics** (query data, check RLS policies, read logs), not as
  the source of truth for schema. Every schema change goes through an Alembic migration file in
  the repo — never applied directly via MCP.
- Prefer a read-only, project-scoped token. Any write performed through MCP must be repeatable
  from the repo (seed script or migration).

## Hard rules (full list in docs/RULES.md)

No cross-module SQL joins · every repo call takes `workspace_id` · no provider SDK outside
`adapters/` · no service-role key for user-facing reads · no score persisted with unverified
evidence or missing provenance · model IDs only in `adapters/llm/models.py` · no business logic
in Supabase Edge Functions.
