"""Microsoft Edge online voices via `edge-tts`.

Free and high quality, with neural voices for Hindi, Telugu, Tamil, Kannada,
Malayalam, Bengali, Marathi, Gujarati, Urdu and Indian English. This is a CLOUD
provider: text is sent to Microsoft's speech service.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from app.core.errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError
from app.document_processing.language import LANGUAGE_NAMES
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo
from app.providers.tts.limiter import AdaptiveLimiter
from app.providers.tts.timing import join_sentences, sentence_times_from_marks

CACHE_TTL = 7 * 24 * 3600


class EdgeTTS(TTSProvider):
    name = "edge"
    display_name = "Microsoft Edge voices (cloud)"
    is_local = False
    # Requests in flight are governed book-wide by an adaptive limiter (below); each
    # chapter keeps a deep window and several chapters run at once so the service
    # always has work queued, even across chapter boundaries.
    max_chunk_parallelism = 32
    max_chapter_parallelism = 6
    mp3_passthrough = True  # CBR MP3 at ~-21 LUFS: chapters are built from its frames
    supports_pitch = True
    supports_timestamps = True
    # Smaller requests return sooner and make a retry cheap.
    max_chunk_chars = 1500
    privacy_note = "Text is sent to Microsoft's online speech service to generate audio. Free, no account needed."

    def __init__(self, cache_dir: Path, timeout: int = 120):
        self.cache_file = cache_dir / "edge_voices.json"
        self.timeout = timeout
        # Measured on real book text (1.5k-char requests, ~2.4x realtime each):
        # 24 in flight -> 50x, 48 -> 93x, 96 -> 155x realtime overall.
        # Raised once chapters stopped needing CPU (MP3 passthrough): the service is the only limit.
        self.limiter = AdaptiveLimiter(start=96, minimum=8, maximum=160)

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "edge-tts is not installed (pip install edge-tts)."
        return True, None

    def _raw_voices(self) -> list[dict]:
        if self.cache_file.exists() and time.time() - self.cache_file.stat().st_mtime < CACHE_TTL:
            try:
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        import edge_tts

        try:
            voices = asyncio.run(edge_tts.list_voices())
        except Exception as exc:
            if self.cache_file.exists():
                return json.loads(self.cache_file.read_text(encoding="utf-8"))
            raise ProviderUnavailableError(self.name, f"Could not reach Microsoft's voice service: {exc}") from exc
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(voices), encoding="utf-8")
        return voices

    def list_voices(self) -> list[VoiceInfo]:
        out = []
        for v in self._raw_voices():
            locale = v.get("Locale", "")
            lang = locale.split("-")[0]
            tags = v.get("VoiceTag", {}) or {}
            styles = ", ".join((tags.get("VoicePersonalities") or [])[:3]) or None
            multilingual = "Multilingual" in v.get("ShortName", "")
            name = v.get("ShortName", "").split("-")[-1].replace("Neural", "").replace("Multilingual", " Multilingual")
            out.append(
                VoiceInfo(
                    provider=self.name,
                    id=v["ShortName"],
                    name=name.strip(),
                    language=lang,
                    locale=locale,
                    accent=_accent(v),
                    gender=(v.get("Gender") or "").lower() or None,
                    style=styles,
                    quality="neural",
                    description=v.get("FriendlyName"),
                    languages=["mul"] if multilingual else [],
                )
            )
        return out

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        import edge_tts

        text, spans = join_sentences(sentences)
        rate = f"{round((options.speed - 1) * 100):+d}%"
        pitch = f"{round(options.pitch * 5):+d}Hz"
        volume = f"{round((options.volume - 1) * 100):+d}%"

        async def run() -> tuple[bytes, list[tuple[str, float, float]]]:
            # A healthy stream sends data every few hundred ms; a silent one is stalled.
            comm = edge_tts.Communicate(text, options.voice_id, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary", receive_timeout=15)
            audio = bytearray()
            marks: list[tuple[str, float, float]] = []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
                elif chunk["type"] in ("WordBoundary", "SentenceBoundary"):
                    start = chunk["offset"] / 1e7
                    marks.append((chunk["text"], start, start + chunk["duration"] / 1e7))
            return bytes(audio), marks

        # A stalled stream is caught by receive_timeout (15s of silence). This overall
        # deadline only bounds pathological cases; it must stay well above the slow
        # tail of healthy requests at high concurrency (p95 ~67s for 1.5k chars at 96).
        deadline = max(self.timeout, 45 + len(text) / 12)
        try:
            with self.limiter.slot():
                audio, marks = asyncio.run(asyncio.wait_for(run(), timeout=deadline))
        except asyncio.TimeoutError as exc:
            self.limiter.congestion()
            raise ProviderTimeoutError(self.name, "Microsoft's speech service timed out.") from exc
        except edge_tts.exceptions.NoAudioReceived as exc:
            raise ProviderError(self.name, "Microsoft's speech service returned no audio for this text.", retryable=True) from exc
        except Exception as exc:
            self.limiter.congestion()
            raise ProviderError(self.name, f"Microsoft's speech service failed: {exc}", retryable=True) from exc
        if not audio:
            raise ProviderError(self.name, "Microsoft's speech service returned no audio.")
        return SynthesisResult(audio=audio, format="mp3", sample_rate=24000, sentence_times=sentence_times_from_marks(text, spans, marks))

    def signature(self, voice_id: str) -> str:
        return f"edge:{voice_id}"


def _accent(v: dict) -> str:
    friendly = v.get("FriendlyName", "")
    if " - " in friendly:
        return friendly.split(" - ", 1)[1]
    lang = v.get("Locale", "").split("-")[0]
    return LANGUAGE_NAMES.get(lang, v.get("Locale", ""))
