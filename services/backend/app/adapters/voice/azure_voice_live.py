"""Azure Speech Voice Live over WebRTC, with the signalling socket held by `api` (D29).

Wire protocol verified by `spikes/voice-live-webrtc.html` and `spikes/run_voice_spike.py`
(2026-10-24): open `wss://<resource>/voice-live/realtime/calls?api-version=..&model=..`,
send `rtc.call.sdp.create` with the browser's offer and the session config, receive
`rtc.call.sdp.created` with the answer. The socket must then stay open for the whole call:
closing it leaves WebRTC "connected" but the buyer silent (D23). The same socket carries
every transcript and `response.done.usage` event, which is why the transcript and the usage
ledger are server-authoritative under D29.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import websockets

from app.adapters.llm.models import (
    TRANSCRIPTION_MODEL,
    VOICE_LIVE_API_VERSION,
    VOICE_LIVE_NATIVE_MODEL,
    VOICE_TYPE_NATIVE,
    VOICE_TYPE_STANDARD,
)
from app.adapters.voice.base import NegotiatedSession, VoiceEvent, VoiceProviderError

log = logging.getLogger("hypersale.voice.azure")

NEGOTIATION_TIMEOUT_SECONDS = 20.0


def voice_config(model: str, voice: str) -> dict[str, str]:
    # `gpt-realtime` takes Azure standard voices; `azure-realtime` takes native ones.
    if model == VOICE_LIVE_NATIVE_MODEL:
        return {"type": VOICE_TYPE_NATIVE, "name": voice}
    return {"type": VOICE_TYPE_STANDARD, "name": voice}


def session_config(instructions: str, voice: str, model: str) -> dict[str, Any]:
    return {
        "modalities": ["text", "audio"],
        "instructions": instructions,
        "voice": voice_config(model, voice),
        "turn_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
        },
        # Without this there is no rep transcript, and D13's attribution check has
        # nothing to verify a quote against.
        "input_audio_transcription": {"model": TRANSCRIPTION_MODEL},
    }


def map_event(message: dict[str, Any], at_ms: int) -> VoiceEvent | None:
    """Translate one provider event into a domain event, or None to ignore it."""
    kind = message.get("type", "")
    if kind == "input_audio_buffer.speech_started":
        return VoiceEvent("rep_started", at_ms, item_id=message.get("item_id"))
    if kind == "conversation.item.input_audio_transcription.completed":
        return VoiceEvent(
            "rep_transcript", at_ms, item_id=message.get("item_id"),
            text=(message.get("transcript") or "").strip(),
        )
    if kind == "response.output_item.added":
        item = message.get("item") or {}
        return VoiceEvent("buyer_started", at_ms, item_id=item.get("id"))
    if kind == "response.audio_transcript.done":
        return VoiceEvent(
            "buyer_transcript", at_ms, item_id=message.get("item_id"),
            text=(message.get("transcript") or "").strip(),
        )
    if kind == "response.done":
        usage = (message.get("response") or {}).get("usage")
        if usage:
            return VoiceEvent("usage", at_ms, usage=usage)
        return None
    if kind in ("error", "rtc.call.error"):
        err = message.get("error") or message
        return VoiceEvent("error", at_ms, detail=str(err)[:500])
    return None


class AzureLiveCall:
    def __init__(self, ws: Any, session: NegotiatedSession, opened_at: float) -> None:
        self._ws = ws
        self.session = session
        self._opened_at = opened_at
        self._closed = False
        # Raw provider event-type counts: the cheapest way to see what a socket really
        # carries (e.g. whether usage arrives here or only on the data channel).
        self.event_counts: dict[str, int] = {}

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._opened_at) * 1000)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = str(message.get("type", "?"))[:60]
                self.event_counts[kind] = self.event_counts.get(kind, 0) + 1
                event = map_event(message, self._now_ms())
                if event is not None:
                    yield event
        except websockets.ConnectionClosed:
            return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001 - hanging up must never raise
            log.debug("voice live socket close raised", exc_info=True)


class AzureVoiceLiveProvider:
    name = "azure"

    def __init__(self, endpoint: str, api_key: str, model: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model

    async def open_call(
        self, *, sdp_offer: str | None, instructions: str, voice: str, user_ref: str
    ) -> AzureLiveCall:
        if not sdp_offer:
            raise VoiceProviderError("An SDP offer is required for a WebRTC call")
        query = urlencode({"api-version": VOICE_LIVE_API_VERSION, "model": self._model})
        url = f"{self._endpoint}?{query}"
        opened_at = time.monotonic()
        try:
            ws = await websockets.connect(
                url,
                subprotocols=["realtime"],
                additional_headers={"api-key": self._api_key},
                open_timeout=NEGOTIATION_TIMEOUT_SECONDS,
                max_size=4 * 1024 * 1024,
            )
        except Exception as exc:  # noqa: BLE001 - any connect failure is an upstream outage
            raise VoiceProviderError(f"Voice Live connect failed: {type(exc).__name__}") from exc

        try:
            await ws.send(json.dumps({
                "type": "rtc.call.sdp.create",
                "sdp_offer": sdp_offer,
                "session": session_config(instructions, voice, self._model),
            }))
            session_ref, answer = await asyncio.wait_for(
                self._await_answer(ws), timeout=NEGOTIATION_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            await ws.close()
            if isinstance(exc, VoiceProviderError):
                raise
            raise VoiceProviderError(f"Voice Live negotiation failed: {type(exc).__name__}") from exc

        session = NegotiatedSession(
            sdp_answer=answer, session_ref=session_ref or f"azure-{int(opened_at * 1000)}",
            model_id=self._model, mode="webrtc",
        )
        return AzureLiveCall(ws, session, opened_at)

    @staticmethod
    async def _await_answer(ws: Any) -> tuple[str | None, str]:
        session_ref = None
        async for raw in ws:
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "session.created":
                session_ref = (message.get("session") or {}).get("id")
            elif kind == "rtc.call.sdp.created":
                return session_ref, message["sdp_answer"]
            elif kind in ("rtc.call.error", "error"):
                detail = (message.get("error") or {}).get("message", "negotiation failed")
                raise VoiceProviderError(f"Voice Live rejected the call: {detail}")
        raise VoiceProviderError("Voice Live closed the socket before answering")
