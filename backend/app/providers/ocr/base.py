from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels
    confidence: float | None = None
    block_id: int | None = None  # engine-provided paragraph/block grouping, if any


@dataclass
class OcrPage:
    lines: list[OcrLine] = field(default_factory=list)
    width: int = 0
    height: int = 0
    engine: str = ""

    @property
    def mean_confidence(self) -> float | None:
        confs = [(ln.confidence, len(ln.text)) for ln in self.lines if ln.confidence is not None]
        total = sum(w for _, w in confs)
        if not total:
            return None
        return sum(c * w for c, w in confs) / total


class OCRProvider(ABC):
    """Recognizes text in page images. Implementations must be thread-safe or
    guard themselves; the analyzer may call them from worker threads."""

    name: str = "base"
    #: ISO 639-1 codes this engine can read with its currently installed models
    supported_languages: set[str] = set()
    #: How many pages the analyzer may OCR at once with this engine
    max_parallel_pages: int = 1

    @abstractmethod
    def is_available(self) -> tuple[bool, str | None]:
        """(available, reason-if-not)."""

    @abstractmethod
    def recognize(self, image_png: bytes, languages: list[str] | None = None) -> OcrPage: ...

    def describe(self) -> dict:
        ok, reason = self.is_available()
        return {
            "name": self.name,
            "available": ok,
            "reason": reason,
            "languages": sorted(self.supported_languages),
            "local": True,
        }
