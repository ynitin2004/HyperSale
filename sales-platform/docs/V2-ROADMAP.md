# V2 Roadmap — Gaps vs Hyperbound (and when to close them)

v1 deliberately competes on **scoring trustworthiness + report speed**, not breadth. This file is
the honest gap list against Hyperbound-class competitors, grouped by theme, each with the trigger
that justifies building it. Nothing here starts before its trigger fires (RULES: scope creep is a
named risk). Ordering within a wave = expected demand.

## Wave 1 — Product depth (first design partners will ask)

| Gap | What Hyperbound-class tools do | Trigger to build |
|---|---|---|
| **Persona auto-generation** | Paste a LinkedIn/company URL → a buyer bot matching that ICP (their signature demo) | ≥2 partners ask; needs enrichment source + review-before-publish step |
| Scenario/persona builder UI | Self-serve creation, cloning, sharing | Partners outgrow the 5 seeded scenarios |
| Methodology packs | MEDDIC/MEDDPICC, SPICED, BANT, Challenger scorecards; custom scorecard builder | A partner runs a named methodology; maps cleanly onto versioned-rubric engine (D16) |
| More call types | Warm calls, gatekeeper, demo, negotiation, renewal | Scenario engine already supports; add when a partner names one |
| Buyer realism dials | Temperament/mood settings, interruptions, "hangs up on a bad opening" | Feedback that the buyer is too polite — likely early |
| Multilingual + voices | Multiple languages, accents, custom voices | Non-English-market partner; big lift (rubric + STT + evals per language) |

## Wave 2 — Team & program layer

| Gap | What they do | Trigger |
|---|---|---|
| Certifications & onboarding programs | Structured curricula, pass thresholds, completion tracking | A partner runs onboarding cohorts through us |
| Gamification | Leaderboards, streaks, tournaments | Usage plateau; cheap on top of `insights` |
| Hiring mode | Candidates do roleplays as screening | A partner asks; **new consent surface — candidates are not employees** |
| Coaching plans over time | AI-suggested longitudinal plans per rep | Enough score history exists (post-M3) |
| Warm-up mode | Short pre-call-block drills | Partner request; trivial on the session engine |

## Wave 3 — Ecosystem integrations

| Gap | What they do | Trigger |
|---|---|---|
| Gong/Chorus/Zoom auto-sync | Auto-pull real calls, score at scale | Partner refuses manual upload (D-scoped in PHASES M3: Zoom first) |
| CRM (Salesforce/HubSpot) | Push scores/activity, pull context | Partner refuses without it |
| Dialers (Orum, Nooks…) | Practice-to-live workflow | Partner request |
| Slack | Digests, nudges, share moments | Cheap; after any of the above |
| Public API/webhooks | Build-your-own integrations | Second partner asks for an integration we won't build |

## Wave 4 — Enterprise

SSO/SAML, SCIM, SOC 2 program, data residency, granular permissions, DPA/security center,
configurable retention by policy. **Trigger:** a real enterprise deal in procurement, not before
(each is weeks of work and zero hiring signal — PRD §1).

## Standing v2 constraints

- Everything routes through the existing scoring engine and provenance rules — no
  parallel scoring paths, ever (the M3 "one pipeline" proof is the precedent).
- Every new AI touchpoint registers in FLOW.md §3 with a guardrail before it ships.
- Every wave item gets a DECISIONS.md entry (with its trigger evidence) when started.
