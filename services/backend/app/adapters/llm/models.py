"""The only place model, voice, and API-version identifiers are allowed to live.

ARCHITECTURE.md makes this a hard rule: an ID hardcoded at a call site is an ID nobody
can audit, and D16 puts `model_id` in the provenance tuple of every score. A score is a
function of the model that produced it, so the identifier has to be greppable from one
file rather than scattered across adapters.
"""
from typing import Final

# --- Voice (D21) ------------------------------------------------------------------
# Azure Speech Voice Live, WebRTC transport. Public preview at time of writing, which
# is acceptable through M2 and must be re-checked before M4 hardening.
VOICE_LIVE_API_VERSION: Final = "2026-01-01-preview"
VOICE_LIVE_MODEL: Final = "gpt-realtime"

# WebRTC negotiation uses `/calls`; the plain `/realtime` path is the WebSocket-only
# transport where the server would have to proxy audio, which D8 forbids.
VOICE_LIVE_CALLS_PATH: Final = "/voice-live/realtime/calls"

# `gpt-realtime` takes Azure standard voices; the `azure-realtime` model takes native
# ones. The two are not interchangeable and the wrong pairing fails at session setup.
VOICE_TYPE_STANDARD: Final = "azure-standard"
VOICE_TYPE_NATIVE: Final = "azure-realtime-native"

# --- Scoring and reports (D19) ----------------------------------------------------
SCORING_MODEL: Final = "claude-opus-5"
VOLUME_MODEL: Final = "claude-haiku-4-5"
# Reserved for disputed-score adjudication, and only once evals show the need (D9).
ADJUDICATION_MODEL: Final = "claude-fable-5"
