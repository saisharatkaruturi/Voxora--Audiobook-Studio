"""Voice catalog, previews and Piper voice installation."""

from __future__ import annotations

import time

from sqlalchemy import select

from app.audio.ffmpeg import decode_to_pcm16
from app.audio.processing import encode_raw, trim_edges
from app.core.config import get_settings
from app.core.errors import ProviderError, ValidationFailed
from app.db.session import session_scope
from app.document_processing.language import LANGUAGE_NAMES
from app.models import AudioAsset
from app.providers.storage import get_storage
from app.providers.tts import SynthesisOptions, VoiceInfo, get_tts_provider, list_tts_providers
from app.services.books import content_hash
from app.services.generation import tmp_dir

SAMPLES = {
    "en": "Hello! This is how I will sound narrating your book. The door slowly opened, and a cold wind swept through the hall.",
    "hi": "नमस्ते! यह आवाज़ आपकी किताब पढ़कर सुनाएगी। धीरे से दरवाज़ा खुला, और ठंडी हवा अंदर आई।",
    "te": "నమస్కారం! ఈ స్వరం మీ పుస్తకాన్ని చదివి వినిపిస్తుంది. మెల్లగా తలుపు తెరుచుకుంది.",
    "ta": "வணக்கம்! இந்தக் குரல் உங்கள் புத்தகத்தைப் படித்துக் காட்டும். கதவு மெதுவாகத் திறந்தது.",
    "kn": "ನಮಸ್ಕಾರ! ಈ ಧ್ವನಿ ನಿಮ್ಮ ಪುಸ್ತಕವನ್ನು ಓದಿ ಕೇಳಿಸುತ್ತದೆ. ಬಾಗಿಲು ನಿಧಾನವಾಗಿ ತೆರೆಯಿತು.",
    "ml": "നമസ്കാരം! ഈ ശബ്ദം നിങ്ങളുടെ പുസ്തകം വായിച്ചു കേൾപ്പിക്കും. വാതിൽ പതുക്കെ തുറന്നു.",
    "bn": "নমস্কার! এই কণ্ঠস্বর আপনার বই পড়ে শোনাবে। দরজাটা ধীরে ধীরে খুলে গেল।",
    "mr": "नमस्कार! हा आवाज तुमचे पुस्तक वाचून दाखवेल. दार हळूच उघडले.",
}

_voice_cache: dict[str, tuple[float, list[VoiceInfo]]] = {}


def list_voices(provider: str | None = None, language: str | None = None, include_catalog: bool = False) -> list[dict]:
    out: list[dict] = []
    for p in list_tts_providers():
        if provider and p.name != provider:
            continue
        ok, _ = p.is_available()
        if not ok and not (p.name == "piper" and include_catalog):
            continue
        cache_key = f"{p.name}:{include_catalog}"
        cached = _voice_cache.get(cache_key)
        if cached and time.time() - cached[0] < 300:
            voices = cached[1]
        else:
            try:
                voices = p.list_voices(include_catalog=True) if (p.name == "piper" and include_catalog) else p.list_voices()
            except Exception:
                voices = []
            _voice_cache[cache_key] = (time.time(), voices)
        for v in voices:
            if language and v.language != language and "mul" not in v.languages:
                continue
            d = v.to_dict()
            d["language_name"] = LANGUAGE_NAMES.get(v.language, v.language)
            d["is_local"] = p.is_local
            d["provider_name"] = p.display_name
            out.append(d)
    return out


def invalidate_voice_cache() -> None:
    _voice_cache.clear()


def preview(provider_name: str, voice_id: str, *, speed: float = 1.0, pitch: float = 0.0, text: str | None = None, language: str | None = None) -> str:
    """Synthesize (or reuse) a short preview. Returns its storage key."""
    provider = get_tts_provider(provider_name)
    ok, reason = provider.is_available()
    if not ok:
        raise ProviderError(provider.name, reason or "Provider unavailable", retryable=False, code="provider_unavailable")
    sample = (text or SAMPLES.get(language or "en") or SAMPLES["en"]).strip()
    if len(sample) > 400:
        sample = sample[:400].rsplit(" ", 1)[0] + "."
    if not sample:
        raise ValidationFailed("Preview text is empty.")
    key = content_hash("preview", provider.signature(voice_id), str(round(speed, 2)), str(round(pitch, 1)), sample)
    storage = get_storage()
    with session_scope() as db:
        asset = db.scalar(select(AudioAsset).where(AudioAsset.cache_key == key))
        if asset and storage.exists(asset.storage_key):
            return asset.storage_key
    from app.document_processing.segmentation import split_sentences

    sentences = [s.text for s in split_sentences(sample)] or [sample]
    result = provider.synthesize(sentences, SynthesisOptions(voice_id=voice_id, speed=speed, pitch=pitch, language=language))
    rate = get_settings().audio_sample_rate
    pcm, _ = trim_edges(decode_to_pcm16(result.audio, result.format, result.sample_rate, rate), rate)
    raw = tmp_dir() / f"preview-{key}.raw"
    out = tmp_dir() / f"preview-{key}.mp3"
    raw.write_bytes(pcm.tobytes())
    try:
        encode_raw(raw, rate, out, "mp3", "64k", normalize=False)
        storage_key = f"cache/previews/{key}.mp3"
        size = storage.save_file(storage_key, out)
    finally:
        raw.unlink(missing_ok=True)
        out.unlink(missing_ok=True)
    with session_scope() as db:
        if db.scalar(select(AudioAsset.id).where(AudioAsset.cache_key == key)) is None:
            db.add(AudioAsset(kind="preview", cache_key=key, storage_key=storage_key, format="mp3", duration=len(pcm) / rate, size_bytes=size, sample_rate=rate))
    return storage_key


def install_piper_voice(ctx) -> dict:
    key = ctx.payload["voice"]
    provider = get_tts_provider("piper")

    def progress(fraction: float) -> None:
        ctx.update(progress=round(fraction * 100, 1), message=f"Downloading voice {key}")

    ctx.update(stage="downloading", message=f"Downloading voice {key}")
    voice = provider.install_voice(key, progress)  # type: ignore[attr-defined]
    invalidate_voice_cache()
    return {"voice": voice.to_dict()}
