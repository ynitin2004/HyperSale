"""The `VoiceProvider` seam D8 promised and never grew.

D8 kept a composed STT->LLM->TTS pipeline as a contained escape hatch, on the strength
of a protocol that did not exist: the OpenAI call was inline in `practice/api.py`, so the
"contained" swap would have touched the request path directly. D21 changed the provider
for real, which is the moment the seam has to become code.

The shape below is deliberately narrow. A provider negotiates a session and returns an
answer the browser can use; it never sees audio. That is not an aesthetic choice -- it is
D8's "server never proxies audio" expressed as a type, so a future provider that wants to
stream audio through the API cannot satisfy this protocol by accident.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NegotiatedSession:
    """What the browser needs to finish a WebRTC handshake, and nothing else.

    `session_ref` is the provider's own identifier. It is the dedupe key the usage
    handler already keys on, so re-delivery of a metering job cannot double-count a
    session (see `workers/handlers.py`).
    """

    sdp_answer: str
    session_ref: str


class VoiceProviderError(RuntimeError):
    """Negotiation failed. Raised instead of leaking a provider-specific exception.

    The request path turns this into a 503: a voice provider being unreachable is an
    upstream outage, not a client error, and the browser should retry rather than
    re-authenticate.
    """


class VoiceProvider(Protocol):
    """A realtime voice backend that negotiates browser-direct media.

    Implementations hold the provider credential and are the only component allowed to
    know the wire format. Nothing above this line imports a provider SDK.
    """

    async def negotiate(
        self,
        *,
        sdp_offer: str,
        instructions: str,
        voice: str,
        user_ref: str,
    ) -> NegotiatedSession:
        """Exchange the browser's SDP offer for an answer, under a configured persona.

        `instructions` is the persona prompt, read from Postgres by the caller and
        passed in here. It is never read from the provider's own agent config: D16
        requires `prompt_version` in the provenance tuple, and a prompt living in a
        vendor console cannot be versioned, reviewed, or diffed.

        `user_ref` is an already-pseudonymous identifier. Implementations must not be
        handed a raw user id -- the caller hashes it first, so a provider-side log can
        never tie a session back to a person.
        """
        ...
