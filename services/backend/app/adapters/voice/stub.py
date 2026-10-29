"""Scripted voice provider for CI, E2E and local demos without spend (D31, RULES §4).

It emits the same domain events a real call does, on a short timer, so the practice module,
transcript persistence, metering and scoring all run unchanged. There is no media: the
browser's stub path shows the server transcript instead of a WebRTC stream.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from app.adapters.voice.base import NegotiatedSession, VoiceEvent

STUB_MODEL = "stub-voice"

# A competent-but-imperfect call: an opener, discovery, one objection, a next-step ask.
# The stub scorer quotes these lines verbatim, so every quote must stay a rep line.
SCRIPT: list[tuple[str, str]] = [
    ("buyer", "Hi, this is the buyer. Who's calling?"),
    ("rep", "Hi, this is Arjun from HyperSale. I'm calling because you asked about rep coaching."),
    ("buyer", "Right, I did. What do you want to know?"),
    ("rep", "How do your new reps practice before they talk to real prospects today?"),
    ("buyer", "Mostly ride-alongs with managers, when they have time."),
    ("rep", "So practice depends on manager time. How many new reps start each quarter?"),
    ("buyer", "About six. Honestly we already have a call recording tool, though."),
    ("rep", "That makes sense. Recording shows what went wrong after the call; we let reps practice before it."),
    ("buyer", "Okay, that's a fair distinction."),
    ("rep", "Could we book thirty minutes next Tuesday at ten to walk through it with your team lead?"),
    ("buyer", "Tuesday at ten works. Send the invite."),
]
TURN_GAP_SECONDS = 0.35
# Plausible token counts so the metering path prices something (D25).
USAGE_PER_RESPONSE = {
    "input_tokens": 900,
    "output_tokens": 60,
    "input_token_details": {"text_tokens": 700, "audio_tokens": 200,
                            "cached_tokens_details": {"text_tokens": 640, "audio_tokens": 0}},
    "output_token_details": {"text_tokens": 10, "audio_tokens": 50},
}


class StubLiveCall:
    def __init__(self, session: NegotiatedSession, gap: float) -> None:
        self.session = session
        self._gap = gap
        self._closed = asyncio.Event()

    async def events(self) -> AsyncIterator[VoiceEvent]:
        at_ms = 0
        for index, (speaker, text) in enumerate(SCRIPT):
            if self._closed.is_set():
                return
            item_id = f"stub_item_{index}"
            duration_ms = 600 + 45 * len(text)
            if speaker == "rep":
                yield VoiceEvent("rep_started", at_ms, item_id=item_id)
                yield VoiceEvent("rep_transcript", at_ms + duration_ms, item_id=item_id, text=text)
            else:
                yield VoiceEvent("buyer_started", at_ms, item_id=item_id)
                yield VoiceEvent("buyer_transcript", at_ms + duration_ms, item_id=item_id, text=text)
                yield VoiceEvent("usage", at_ms + duration_ms, usage=USAGE_PER_RESPONSE)
            at_ms += duration_ms + 400
            try:
                await asyncio.wait_for(self._closed.wait(), timeout=self._gap)
                return
            except TimeoutError:
                pass
        # Stay "connected" until hung up, like a real call after the buyer stops talking.
        await self._closed.wait()

    async def close(self) -> None:
        self._closed.set()


class StubVoiceProvider:
    name = "stub"

    def __init__(self, gap_seconds: float = TURN_GAP_SECONDS) -> None:
        self._gap = gap_seconds

    async def open_call(
        self, *, sdp_offer: str | None, instructions: str, voice: str, user_ref: str
    ) -> StubLiveCall:
        session = NegotiatedSession(
            sdp_answer=None, session_ref=f"stub-{uuid.uuid4()}", model_id=STUB_MODEL, mode="stub"
        )
        return StubLiveCall(session, self._gap)
