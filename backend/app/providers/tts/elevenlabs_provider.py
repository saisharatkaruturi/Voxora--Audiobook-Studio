"""ElevenLabs (cloud). Uses the /with-timestamps endpoint for exact sentence timings."""

from __future__ import annotations

import base64

import httpx

from app.core.errors import ProviderError, ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo
from app.providers.tts.timing import join_sentences

API = "https://api.elevenlabs.io/v1"


class ElevenLabsTTS(TTSProvider):
    name = "elevenlabs"
    display_name = "ElevenLabs (cloud)"
    is_local = False
    max_chunk_parallelism = 3
    supports_timestamps = True
    max_chunk_chars = 2400
    requires_api_key = True
    privacy_note = "Text is sent to ElevenLabs to generate audio. Usage counts against your ElevenLabs character quota."

    def __init__(self, api_key: str | None, model: str, timeout: int = 120):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._voices: list[VoiceInfo] | None = None

    def is_available(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "Set ELEVENLABS_API_KEY to use ElevenLabs voices."
        return True, None

    def _headers(self) -> dict:
        return {"xi-api-key": self.api_key or ""}

    def list_voices(self) -> list[VoiceInfo]:
        if not self.api_key:
            return []
        if self._voices is not None:
            return self._voices
        try:
            resp = httpx.get(f"{API}/voices", headers=self._headers(), timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Could not load ElevenLabs voices: {exc}") from exc
        voices = []
        for v in resp.json().get("voices", []):
            labels = v.get("labels") or {}
            voices.append(
                VoiceInfo(
                    provider=self.name,
                    id=v["voice_id"],
                    name=v.get("name", v["voice_id"]),
                    language=(labels.get("language") or "en")[:2],
                    accent=(labels.get("accent") or "").title() or None,
                    gender=labels.get("gender"),
                    style=labels.get("use_case") or labels.get("description"),
                    quality="neural",
                    description=v.get("description"),
                    languages=["mul"] if "multilingual" in self.model else [],
                    meta={"preview_url": v.get("preview_url")},
                )
            )
        self._voices = voices
        return voices

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "", retryable=False)
        text, spans = join_sentences(sentences)
        body = {
            "text": text,
            "model_id": self.model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": max(0.7, min(options.speed, 1.2))},
        }
        try:
            resp = httpx.post(
                f"{API}/text-to-speech/{options.voice_id}/with-timestamps?output_format=mp3_44100_128",
                json=body,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.name, "ElevenLabs timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Could not reach ElevenLabs: {exc}") from exc
        if resp.status_code == 429:
            raise ProviderRateLimitError(self.name, "ElevenLabs rate limit reached. Generation will retry automatically.")
        if resp.status_code in (401, 403):
            raise ProviderError(self.name, "ElevenLabs rejected the API key or your quota is exhausted.", retryable=False)
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"ElevenLabs error {resp.status_code}: {resp.text[:200]}", retryable=resp.status_code >= 500)
        data = resp.json()
        audio = base64.b64decode(data["audio_base64"])
        times = None
        align = data.get("alignment") or {}
        starts, ends = align.get("character_start_times_seconds"), align.get("character_end_times_seconds")
        if starts and ends and len(starts) == len(text):
            times = [(starts[a], ends[max(b - 1, a)]) for a, b in spans]
        return SynthesisResult(audio=audio, format="mp3", sample_rate=44100, sentence_times=times)

    def signature(self, voice_id: str) -> str:
        return f"elevenlabs:{self.model}:{voice_id}"

    def estimate_cost(self, characters: int) -> dict | None:
        # Plans are credit-based; report credits, not money.
        return {"currency": "credits", "amount": characters, "basis": "ElevenLabs bills 1 credit per character on most models"}
