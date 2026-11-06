from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class VoiceInfo:
    provider: str
    id: str
    name: str
    language: str  # ISO 639-1 ("te"), or "mul" for multilingual voices
    locale: str | None = None  # "te-IN"
    accent: str | None = None  # human label, e.g. "Indian English"
    gender: str | None = None  # only when the provider exposes it
    style: str | None = None
    quality: str | None = None
    installed: bool = True
    description: str | None = None
    languages: list[str] = field(default_factory=list)  # extra languages the provider documents
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SynthesisOptions:
    voice_id: str
    speed: float = 1.0  # 0.5..2.0, baked into the audio
    pitch: float = 0.0  # semitones-ish, -10..10; ignored when unsupported
    volume: float = 1.0  # 0..2
    language: str | None = None
    sentence_pause_ms: int = 250


@dataclass
class SynthesisResult:
    audio: bytes
    format: str  # wav | mp3 | pcm_s16le
    sample_rate: int
    # (start, end) seconds for each input sentence, relative to the start of `audio`.
    # None when the provider can't report timings (the caller approximates).
    sentence_times: list[tuple[float, float]] | None = None


class TTSProvider(ABC):
    name: str = "base"
    display_name: str = "Base"
    is_local: bool = True  # False => text is sent to a third-party service
    supports_pitch: bool = False
    supports_timestamps: bool = False
    max_chunk_chars: int = 1000
    # How many chunks may be synthesized at once. Local engines size this from the
    # hardware; cloud engines keep it modest to respect provider rate limits.
    max_chunk_parallelism: int = 1
    #: Chapters that may synthesize at once (cloud services: >1 keeps the pipe full)
    max_chapter_parallelism: int = 1
    #: Returns CBR MP3 that chapters can be built from directly (no decode/re-encode)
    mp3_passthrough: bool = False
    requires_api_key: bool = False
    privacy_note: str = ""

    @abstractmethod
    def is_available(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    def list_voices(self) -> list[VoiceInfo]: ...

    @abstractmethod
    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult: ...

    def signature(self, voice_id: str) -> str:
        """Anything that changes output for identical text (model version...). Part of the cache key."""
        return ""

    def estimate_cost(self, characters: int) -> dict | None:
        """Only return a price when it can be computed reliably from published pricing."""
        return None

    def describe(self) -> dict:
        ok, reason = self.is_available()
        return {
            "name": self.name,
            "display_name": self.display_name,
            "available": ok,
            "reason": reason,
            "is_local": self.is_local,
            "supports_pitch": self.supports_pitch,
            "supports_timestamps": self.supports_timestamps,
            "requires_api_key": self.requires_api_key,
            "privacy_note": self.privacy_note,
            "parallelism": self.max_chunk_parallelism,
        }
