# PRD — AI Sales Performance Platform

## 1. What this project does (plain language)

Sales reps are bad at cold calls and discovery calls until they've done hundreds of them — and
today they practice on real prospects, burning real pipeline, or in awkward manager roleplays
that nobody schedules. This product gives every rep an unlimited, judgment-free sparring partner:

1. A rep picks a **scenario** (e.g. "cold call a skeptical VP of Engineering at a 200-person
   fintech") and clicks start.
2. They have a **real spoken conversation** with an AI that plays the buyer — it answers the
   phone annoyed, raises objections, goes quiet, asks hard questions, exactly like the persona
   defines.
3. The session is recorded and transcribed live. When the rep hangs up, the system **scores the
   call** against a rubric (opening, discovery, objection handling, next steps…).
4. Every piece of criticism carries a **clickable, timestamped quote** from the transcript —
   the rep clicks it and hears themselves at that exact moment. The system verifies in code that
   every quote really exists and really came from the rep, so feedback can be trusted.
5. The rep gets **3 drills** to practice next; their scores build a progress history.
6. **Managers** assign scenarios, review attempts, and compare the team on the same rubric. In a
   later phase, real recorded sales calls are uploaded and scored through the identical pipeline,
   so practice scores and real-call scores are directly comparable.

Business model: seat-based B2B SaaS for English-speaking SaaS sales teams (USD). Immediate goal
of the build: a hiring-grade live demo plus measured scoring quality (see §5).

## 2. Users & jobs-to-be-done

| User | Job | Product answer |
|---|---|---|
| SDR / AE | Get confident before real calls | On-demand voice roleplay, no scheduling, no embarrassment |
| SDR / AE | Tell me what I did wrong, with proof | Evidence-verified, speaker-verified, timestamped scorecard |
| SDR / AE | Tell me what to practice next | 3 recommended drills per report |
| Manager | Ramp reps without burning my calendar | Assign scenarios, review attempts async |
| Manager | Coach from real calls, not memory | Uploads scored through the same rubric pipeline (Phase M3) |
| Manager | Compare the team objectively | Same immutable rubric versions across everyone |
| Admin | Control access, consent, retention, spend | Roles, consent/retention settings, deletion job, metering, audit log |

## 3. Why existing tools fail (and our answer)

1. **Untrustworthy feedback** — LLM scorers praise things never said, cite quotes that don't
   exist, or attribute the AI's own words to the rep. → We verify evidence **in code**: the quote
   must exist in the transcript AND fall inside the right speaker's turn, or the score is
   rejected and retried. What code can't verify (does the quote actually support the claim?) we
   measure with sampled human judgment and never claim as zero.
2. **Unreproducible scores** — rubrics and prompts drift silently. → Every score records
   `(rubric_version, prompt_version, model_id, metrics_version)`, all immutable once referenced.
3. **Vibes-based coaching** — → Deterministic metrics (talk ratio, monologue length, question
   mix, next-step-with-date) computed outside the model, rendered instantly.
4. **Scoring absent evidence** — → Criteria are scenario-scoped; `insufficient_evidence` is a
   first-class outcome, not a low score.
5. **Latency kills the loop** — → Transcript is server-side the moment the call ends; metrics in
   <1 s, full report p95 <30 s.

## 4. Launch scope (M0–M2)

**In:** voice roleplay loop end-to-end · 5 hand-crafted seeded personas/scenarios · rubric v1
(7 criteria, scenario-scoped) · evidence-verified scoring + deterministic metrics · report page
with audio-seek · gold set labeled by external sales managers + eval harness in CI · manager
assign/review/compare · auth, workspaces, tenancy, metering from day one.

**Out (trigger to build):** scenario builder UI (design-partner demand) · CRM/dialer/Slack
(partner refuses without it) · billing (someone asks to pay — then Stripe) · Zoom ingestion (M3,
on request) · enterprise SSO/SCIM/residency (enterprise deal) · everything in `V2-ROADMAP.md`.

## 5. Success metrics

| Metric | Target |
|---|---|
| Invite → first scored roleplay | < 10 min |
| Session start (click → talking) | < 5 s |
| Deterministic metrics on screen after call end | < 1 s |
| Full scored report (roleplay) | p95 < 30 s |
| Rubric agreement (weighted kappa + MAE vs external human labels) | Published **with inter-rater ceiling**; CI-gated |
| Fabricated-quote rate / misattributed-quote rate | 0 — code-enforced |
| Evidence relevance | Sampled, human-judged; tracked, never claimed zero |
| Practices per rep per week | ≥ 3 |
| Cost per session | Measured in M0 before product code; drives caps & pricing |

## 6. Competitive reference

Hyperbound is the category benchmark. The v1 gap list and the plan for closing it lives in
`V2-ROADMAP.md` — v1 deliberately competes on **scoring trustworthiness and speed**, not
feature breadth.
