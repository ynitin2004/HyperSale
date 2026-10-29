"""The `VoiceProvider` seam (D8), reshaped by D29 into a brokered live call.

D8 promised a narrow protocol and "server never proxies audio". D23 then measured that a
Voice Live call dies with its signalling socket, and D29 put that socket in `api`. So the
shape is now: the provider opens a call from the browser's SDP offer, returns the SDP answer,
and exposes the call's control-plane events as *domain* events. Audio still never passes
through here - only SDP and JSON events do - and nothing above this module sees a provider's
wire format.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EventKind = Literal[
    "rep_started",      # rep began speaking (VAD)
    "rep_transcript",   # final transcript for a rep utterance
    "buyer_started",    # buyer response began
    "buyer_transcript", # final transcript for a buyer response
    "usage",            # token usage for one provider response
    "error",            # provider-reported error; the call may continue
]


@dataclass(frozen=True)
class VoiceEvent:
    kind: EventKind
    # Milliseconds since the call was opened, on the api's clock. One clock for both
    # speakers keeps transcript ordering and recording seeks consistent.
    at_ms: int
    item_id: str | None = None
    text: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    detail: str | None = None


@dataclass(frozen=True)
class NegotiatedSession:
    """What the browser needs to finish a WebRTC handshake, and nothing else.

    `sdp_answer` is None for the stub provider, which has no media path (D31).
    `session_ref` is the provider's identifier and the usage dedupe key.
    """

    sdp_answer: str | None
    session_ref: str
    model_id: str
    mode: Literal["webrtc", "stub"]


class VoiceProviderError(RuntimeError):
    """Negotiation failed. The request path turns this into a 502/503."""


class LiveCall(Protocol):
    session: NegotiatedSession

    def events(self) -> AsyncIterator[VoiceEvent]:
        """Domain events until the call ends. Ending the iterator means the call is over."""
        ...

    async def close(self) -> None:
        """Hang up. Idempotent. For Voice Live this closes the signalling socket (D23)."""
        ...


class VoiceProvider(Protocol):
    name: str

    async def open_call(
        self,
        *,
        sdp_offer: str | None,
        instructions: str,
        voice: str,
        user_ref: str,
    ) -> LiveCall:
        """Open a live call under a persona prompt read from Postgres by the caller.

        `user_ref` is already pseudonymous; implementations never receive a raw user id.
        """
        ...
