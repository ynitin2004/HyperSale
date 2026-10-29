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
# The Voice Live model that takes native voices instead of standard ones.
VOICE_LIVE_NATIVE_MODEL: Final = "azure-realtime"
# Rep-side transcription inside the realtime session; D13 verifies quotes against it.
TRANSCRIPTION_MODEL: Final = "whisper-1"
# OpenAI direct realtime, retired by D21; kept only for the legacy M0 settings field.
OPENAI_REALTIME_MODEL: Final = "gpt-realtime-2.1"
VOICE_TYPE_NATIVE: Final = "azure-realtime-native"

# Default Voice Live voice when a persona does not name one. `gpt-realtime` takes Azure
# standard voices; Indian-English female suits the first persona's region (D21).
DEFAULT_VOICE: Final = "en-IN-NeerjaNeural"

# --- Scoring and reports (D19, amended by D28) ------------------------------------
# D28: every Claude model on the available gateway returns "no channel"; gpt-5.6-sol is
# reached through the same official Anthropic SDK and passed Spike 3 (D13 0/0, 3 runs).
SCORING_MODEL: Final = "gpt-5.6-sol"
# The documented Claude choice, kept so switching back is one constant (D28 revisit).
SCORING_MODEL_CLAUDE: Final = "claude-opus-5"
VOLUME_MODEL: Final = "claude-haiku-4-5"
# Reserved for disputed-score adjudication, and only once evals show the need (D9).
ADJUDICATION_MODEL: Final = "claude-fable-5"

# --- Prices (RULES §1: prices live only here) -------------------------------------
# micro-USD per 1M tokens. gpt-5.6-sol: $4 in / $0.40 cached / $20 out, OpenAI list price
# (promotional through 2026-11-21, checked 2026-10-29). Opus 5: $5 / $0.50 / $25.
MODEL_PRICES_MICROUSD_PER_1M: Final[dict[str, tuple[int, int, int]]] = {
    "gpt-5.6-sol": (4_000_000, 400_000, 20_000_000),
    "claude-opus-5": (5_000_000, 500_000, 25_000_000),
    "claude-haiku-4-5": (1_000_000, 100_000, 5_000_000),
}
