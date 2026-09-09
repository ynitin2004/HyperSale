# Design System & UX

Confident sales-coach feel: information-dense but calm. WCAG AA contrast minimum, responsive,
full keyboard support. Design tokens (color, spacing, type scale, radius) defined before visual
work; shadcn/ui as the component base. Every screen defines loading / empty / error /
permission-denied states **before** visual polish.

## 1. Core routes

Onboarding → Dashboard → Scenario catalog → Live roleplay → Report → Manager (assignments,
attempts, team comparison) → Settings (workspace, members, retention/consent).

## 2. The roleplay screen (the screen that matters)

1. **Preflight** (see §4 — mandatory, cannot be skipped on first session).
2. **Connection states:** explicit connecting / connected / degraded / reconnecting UI. Never a
   dead mic with no signal to the user.
3. **In-session:** live transcript, recording indicator, pause/end, elapsed time + remaining cap,
   live mic-level meter (so the rep can *see* they're being heard).
4. **Graceful reconnect** on network blips; chunked upload continues independently.
5. **Scorecard:** deterministic metrics strip first (instant) → criteria stream in →
   `insufficient_evidence` rendered neutral and explained, never styled as failure → evidence
   quotes labeled with speaker; click seeks audio to `start_ms`.
6. **Next:** 3 recommended drills.

## 3. Latency UX rules

- Never show a spinner where content can stream: metrics render instantly, criteria appear one
  by one, transcript scrolls live.
- Perceived start matters more than actual start: begin WebRTC setup *while* the scenario brief
  is on screen ("Your buyer is Priya, VP Eng… connecting…").
- Show elapsed-vs-budget in dev builds for every stage in ARCHITECTURE.md §5 so latency
  regressions are seen, not discovered.
- If the full report exceeds 30 s, the UI says what it's still doing — never a frozen bar.

## 4. Audio-reliability playbook ("no sound" must be impossible to hit silently)

The #1 support ticket in any voice product is "I can't hear it / it can't hear me." Every cause
below has a designed detection + response:

| Cause | Detection | Response |
|---|---|---|
| Autoplay policy blocks remote audio (most common) | `audioEl.play()` promise rejects; `AudioContext.state === "suspended"` | Audio is only started from the user's click on **Start call**; if still blocked, full-screen "Tap to enable audio" prompt |
| Mic permission denied | `getUserMedia` rejection type | Dedicated permission-denied state with browser-specific re-enable instructions; never a generic error |
| Wrong input/output device | Preflight | Preflight: pick devices, **speak-and-see** mic level meter, play a test tone through the chosen output; store per-device choice |
| Bluetooth headset profile flip (A2DP↔HFP) | Sample-rate/device change events | Warn in preflight when a Bluetooth device is selected; recommend wired/built-in for best quality |
| Device unplugged mid-call | `devicechange` event; track `ended`/`mute` events | Auto-pause session, re-run device pick, resume |
| Rep speaking but nothing transmitted | Mic RMS ≈ 0 for > 5 s while session active | Inline banner: "We can't hear you — check your mic"; breadcrumb to Sentry |
| Buyer audio arriving but inaudible | Remote track stats show packets but output RMS ≈ 0 | "Can't hear the buyer?" recovery affordance: re-attach element, re-select output |
| Network degradation | WebRTC connection-state + stats (RTT, packet loss) | Degraded banner → reconnecting state → clean end with partial transcript preserved (never a hang) |
| Echo / feedback | Constraints | `echoCancellation: true, noiseSuppression: true, autoGainControl: true` on `getUserMedia`; warn on speaker+mic (no headset) setups |

Instrumentation rule (also in RULES.md): every audio state transition is a Sentry breadcrumb, so
any "no sound" report arrives with its full causal trail.

## 5. Report page details

- Transcript is the spine: scores annotate it, not the other way around.
- Clicking evidence highlights the transcript span AND seeks audio; keyboard: `←/→` between
  evidence moments.
- Speaker attribution visible on every quote (rep vs buyer) — this is a trust feature, show it.
- Degraded states are honest: recording upload failed → "audio unavailable, transcript-based
  report"; verification retries exhausted → visibly degraded report, never silently weaker.

## 6. Empty/demo states

- New workspace lands on 5 seeded scenarios with one "try this first" highlighted — a rep must
  reach their first roleplay without reading anything.
- A permanent demo workspace with pre-seeded sessions and reports exists for interviews (never
  show an empty dashboard in a demo).
