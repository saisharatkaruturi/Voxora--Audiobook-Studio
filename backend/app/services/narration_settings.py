"""Per-book narration settings (voice + audio options), with validated defaults."""

from __future__ import annotations

from app.core.config import get_settings

SPEEDS = [0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]

DEFAULTS = {
    "provider": None,  # filled from TTS_PROVIDER
    "voice_id": None,
    "language_voices": {},  # {"te": {"provider": "edge", "voice_id": "te-IN-ShrutiNeural"}}
    "speed": 1.0,
    "pitch": 0.0,
    "volume": 1.0,
    "sentence_pause_ms": 250,
    "paragraph_pause_ms": 650,
    "heading_pause_ms": 1100,
    "chapter_pause_ms": 2000,
    "narration_cleanup": True,
    "ai_ocr_repair": False,
    "cast_mode": False,
    "announce_chapter_titles": True,
    "format": None,  # filled from AUDIO_DEFAULT_FORMAT
    "bitrate": None,
    "normalize": True,
    "compress": False,
    "shorten_long_pauses": True,
    "build_full_audiobook": False,  # downloads join chapters on demand; no second copy
    "content_mode": "narrative",  # narrative | full | custom (which sections are narrated)
}

# Settings that change the generated audio (part of each chapter's content hash).
AUDIO_AFFECTING = [
    "provider", "voice_id", "language_voices", "speed", "pitch", "volume", "sentence_pause_ms", "paragraph_pause_ms",
    "heading_pause_ms", "chapter_pause_ms", "narration_cleanup", "ai_ocr_repair", "cast_mode", "announce_chapter_titles",
    "format", "bitrate", "normalize", "compress", "shorten_long_pauses",
]


def default_voice_for(provider: str, language: str | None) -> str | None:
    s = get_settings()
    if provider == "piper":
        from app.providers.tts import get_tts_provider

        voices = [v for v in get_tts_provider("piper").list_voices() if v.installed]
        match = [v for v in voices if v.language == (language or "en")]
        if match:
            return match[0].id
        return s.piper_default_voice if any(v.id == s.piper_default_voice for v in voices) else (voices[0].id if voices else None)
    if provider == "edge":
        return {
            "en": "en-US-AriaNeural", "hi": "hi-IN-SwaraNeural", "te": "te-IN-ShrutiNeural", "ta": "ta-IN-PallaviNeural",
            "kn": "kn-IN-SapnaNeural", "ml": "ml-IN-SobhanaNeural", "bn": "bn-IN-TanishaaNeural", "mr": "mr-IN-AarohiNeural",
            "gu": "gu-IN-DhwaniNeural", "ur": "ur-IN-GulNeural",
        }.get(language or "en", "en-US-EmmaMultilingualNeural")
    if provider == "openai":
        return "nova"
    try:
        from app.providers.tts import get_tts_provider

        voices = get_tts_provider(provider).list_voices()
        match = [v for v in voices if v.language == language] or voices
        return match[0].id if match else None
    except Exception:
        return None


def resolve(narration: dict | None, language: str | None = None) -> dict:
    s = get_settings()
    merged = {**DEFAULTS, **{k: v for k, v in (narration or {}).items() if k in DEFAULTS and v is not None}}
    merged["provider"] = merged["provider"] or s.tts_provider
    merged["format"] = merged["format"] or s.audio_default_format
    merged["bitrate"] = merged["bitrate"] or s.audio_default_bitrate
    if not merged["voice_id"]:
        merged["voice_id"] = default_voice_for(merged["provider"], language)
    merged["speed"] = min(max(float(merged["speed"]), 0.5), 2.0)
    merged["pitch"] = min(max(float(merged["pitch"]), -10.0), 10.0)
    merged["volume"] = min(max(float(merged["volume"]), 0.0), 2.0)
    for key in ("sentence_pause_ms", "paragraph_pause_ms", "heading_pause_ms", "chapter_pause_ms"):
        merged[key] = int(min(max(int(merged[key]), 0), 10000))
    return merged


def audio_signature(settings: dict) -> dict:
    return {k: settings.get(k) for k in AUDIO_AFFECTING}
