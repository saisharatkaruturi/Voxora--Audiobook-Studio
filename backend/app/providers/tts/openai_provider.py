"""OpenAI-compatible speech API (`POST /audio/speech`).

Works with OpenAI and compatible servers (set OPENAI_TTS_BASE_URL). CLOUD provider.
"""

from __future__ import annotations

import httpx

from app.core.errors import ProviderError, ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo
from app.providers.tts.timing import join_sentences

OPENAI_VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
# Published per-character prices (USD per 1M characters). Token-priced models are omitted
# because their cost can't be estimated reliably from character counts.
PRICE_PER_MILLION = {"tts-1": 15.0, "tts-1-hd": 30.0}


class OpenAITTS(TTSProvider):
    name = "openai"
    display_name = "OpenAI TTS (cloud)"
    is_local = False
    max_chunk_parallelism = 4
    supports_timestamps = False
    max_chunk_chars = 3800
    requires_api_key = True
    privacy_note = "Text is sent to OpenAI (or your configured compatible server) to generate audio."

    def __init__(self, api_key: str | None, base_url: str, model: str, timeout: int = 120):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "Set OPENAI_TTS_API_KEY (or TTS_API_KEY) to use OpenAI voices."
        return True, None

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(
                provider=self.name,
                id=v,
                name=v.title(),
                language="en",
                locale=None,
                accent="Multilingual, optimized for English",
                quality="neural",
                description=f"OpenAI '{v}' voice ({self.model}). OpenAI documents multilingual support; quality is best in English.",
                languages=["mul"],
            )
            for v in OPENAI_VOICES
        ]

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "", retryable=False)
        text, _ = join_sentences(sentences)
        body = {"model": self.model, "voice": options.voice_id, "input": text, "response_format": "wav", "speed": max(0.25, min(options.speed, 4.0))}
        try:
            resp = httpx.post(
                f"{self.base_url}/audio/speech",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.name, "OpenAI's speech API timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Could not reach the OpenAI speech API: {exc}") from exc
        if resp.status_code == 429:
            raise ProviderRateLimitError(self.name, "OpenAI rate limit reached. Generation will retry automatically.")
        if resp.status_code in (401, 403):
            raise ProviderError(self.name, "OpenAI rejected the API key. Check OPENAI_TTS_API_KEY.", retryable=False)
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"OpenAI speech API error {resp.status_code}: {resp.text[:200]}", retryable=resp.status_code >= 500)
        return SynthesisResult(audio=resp.content, format="wav", sample_rate=24000, sentence_times=None)

    def signature(self, voice_id: str) -> str:
        return f"openai:{self.model}:{voice_id}"

    def estimate_cost(self, characters: int) -> dict | None:
        price = PRICE_PER_MILLION.get(self.model)
        if price is None:
            return None
        return {"currency": "USD", "amount": round(characters / 1_000_000 * price, 2), "basis": f"{self.model} at ${price}/1M characters"}
