"""TTS provider registry. Providers are selected by name (TTS_PROVIDER / per-book
settings) so no vendor logic leaks into the rest of the application."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo


@lru_cache
def _registry() -> dict[str, TTSProvider]:
    settings = get_settings()
    from app.providers.tts.edge_provider import EdgeTTS
    from app.providers.tts.elevenlabs_provider import ElevenLabsTTS
    from app.providers.tts.openai_provider import OpenAITTS
    from app.providers.tts.piper_provider import PiperTTS
    from app.providers.tts.sapi_provider import SapiTTS

    all_providers: dict[str, TTSProvider] = {
        "piper": PiperTTS(settings.piper_voices_path, sessions=settings.piper_sessions or None),
        "sapi": SapiTTS(),
        "edge": EdgeTTS(settings.piper_voices_path.parent, settings.tts_timeout_seconds),
        "openai": OpenAITTS(
            settings.openai_tts_api_key or settings.tts_api_key,
            settings.openai_tts_base_url,
            settings.openai_tts_model,
            settings.tts_timeout_seconds,
        ),
        "elevenlabs": ElevenLabsTTS(settings.elevenlabs_api_key or settings.tts_api_key, settings.elevenlabs_model, settings.tts_timeout_seconds),
    }
    enabled = set(settings.tts_enabled_providers) | {settings.tts_provider}
    return {k: v for k, v in all_providers.items() if k in enabled}


def list_tts_providers() -> list[TTSProvider]:
    return list(_registry().values())


def get_tts_provider(name: str | None = None) -> TTSProvider:
    name = name or get_settings().tts_provider
    provider = _registry().get(name)
    if provider is None:
        raise ProviderUnavailableError(name, f"TTS provider '{name}' is not enabled on this server.", retryable=False)
    return provider


__all__ = ["SynthesisOptions", "SynthesisResult", "TTSProvider", "VoiceInfo", "get_tts_provider", "list_tts_providers"]
