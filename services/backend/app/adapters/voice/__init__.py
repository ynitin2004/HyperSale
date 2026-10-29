from app.adapters.voice.base import (
    LiveCall,
    NegotiatedSession,
    VoiceEvent,
    VoiceProvider,
    VoiceProviderError,
)
from app.config import Settings, get_settings
from app.errors import AppError


def build_voice_provider(settings: Settings | None = None) -> VoiceProvider:
    """The only place a voice provider is chosen. `VOICE_PROVIDER=stub` for CI/E2E (D31)."""
    settings = settings or get_settings()
    if settings.voice_provider == "stub":
        from app.adapters.voice.stub import StubVoiceProvider

        return StubVoiceProvider(gap_seconds=settings.stub_voice_turn_gap_seconds)
    if settings.voice_provider == "azure":
        if not (settings.azure_voice_live_endpoint and settings.azure_voice_live_api_key):
            raise AppError(
                "voice_not_configured",
                "Set AZURE_VOICE_LIVE_ENDPOINT and AZURE_VOICE_LIVE_API_KEY",
                status_code=503,
            )
        from app.adapters.voice.azure_voice_live import AzureVoiceLiveProvider

        return AzureVoiceLiveProvider(
            settings.azure_voice_live_endpoint,
            settings.azure_voice_live_api_key,
            settings.azure_voice_live_model,
        )
    raise AppError("voice_not_configured", f"Unknown VOICE_PROVIDER {settings.voice_provider!r}",
                   status_code=503)


__all__ = [
    "LiveCall",
    "NegotiatedSession",
    "VoiceEvent",
    "VoiceProvider",
    "VoiceProviderError",
    "build_voice_provider",
]
