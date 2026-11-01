"""Speech to text with speaker separation for uploaded calls (M3, D43).

`AzureTranscriber` calls Azure Speech fast transcription on the Voice Live resource, so there is
no second vendor. `StubTranscriber` (D31) replays the stub voice script, so tests and E2E exercise
the same pipeline without a provider.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.adapters.llm.models import TRANSCRIBE_API_VERSION, TRANSCRIBE_MODEL
from app.adapters.voice.stub import SCRIPT
from app.config import Settings, get_settings
from app.errors import AppError

TIMEOUT_SECONDS = 300


class TranscriptionError(Exception):
    """The provider could not transcribe the audio; the queue retries this."""


@dataclass(frozen=True)
class Phrase:
    speaker: int
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Transcript:
    phrases: list[Phrase]
    duration_ms: int
    model_id: str
    provider: str


class Transcriber(Protocol):
    async def transcribe(self, audio: bytes, mime: str | None) -> Transcript: ...


class AzureTranscriber:
    def __init__(self, endpoint: str, api_key: str) -> None:
        host = urlparse(endpoint if "://" in endpoint else f"https://{endpoint}").hostname
        self._url = f"https://{host}/speechtotext/transcriptions:transcribe?api-version={TRANSCRIBE_API_VERSION}"
        self._api_key = api_key

    async def transcribe(self, audio: bytes, mime: str | None) -> Transcript:
        definition = {"locales": ["en-US"], "diarization": {"enabled": True, "maxSpeakers": 2}}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    self._url, headers={"Ocp-Apim-Subscription-Key": self._api_key},
                    files={"audio": ("call", audio, mime or "application/octet-stream"),
                           "definition": (None, json.dumps(definition))},
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code != 200:
            raise TranscriptionError(f"{response.status_code}: {response.text[:300]}")
        return parse_azure(response.json())


def parse_azure(body: dict) -> Transcript:
    """Pure, so the provider's shape is unit-tested."""
    phrases = [
        Phrase(speaker=p.get("speaker", 0), text=p["text"], start_ms=p["offsetMilliseconds"],
               end_ms=p["offsetMilliseconds"] + p["durationMilliseconds"])
        for p in body.get("phrases", []) if p.get("text")
    ]
    return Transcript(sorted(phrases, key=lambda p: p.start_ms), body.get("durationMilliseconds", 0),
                      TRANSCRIBE_MODEL, "azure")


class StubTranscriber:
    async def transcribe(self, audio: bytes, mime: str | None) -> Transcript:
        phrases = [Phrase(speaker=1 if speaker == "buyer" else 2, text=text, start_ms=i * 4000,
                          end_ms=i * 4000 + 3000) for i, (speaker, text) in enumerate(SCRIPT)]
        return Transcript(phrases, len(SCRIPT) * 4000, "stub-transcriber", "stub")


def build_transcriber(settings: Settings | None = None) -> Transcriber:
    settings = settings or get_settings()
    if settings.voice_provider == "stub":
        return StubTranscriber()
    if not (settings.azure_voice_live_endpoint and settings.azure_voice_live_api_key):
        raise AppError("transcription_not_configured", "Azure Speech is not configured", status_code=503)
    return AzureTranscriber(settings.azure_voice_live_endpoint, settings.azure_voice_live_api_key)
