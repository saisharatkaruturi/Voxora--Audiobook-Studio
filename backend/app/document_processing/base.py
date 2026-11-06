"""Format-independent representation of an extracted document.

Every extractor (PDF, DOCX, EPUB, TXT, image) produces an `ExtractedDocument`.
Cleaning and structure detection only ever see this representation, so adding a
new input format means writing one extractor.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Block:
    """A paragraph-like unit of text in reading order."""

    text: str
    kind: str = "text"  # text | heading
    level: int | None = None  # heading level (1 = most prominent)
    page: int | None = None  # 1-based source page, when meaningful
    font_size: float | None = None
    bold: bool = False
    ocr_confidence: float | None = None
    meta: dict = field(default_factory=dict)

    @property
    def is_heading(self) -> bool:
        return self.kind == "heading"


@dataclass
class TocEntry:
    title: str
    level: int = 1
    page: int | None = None  # PDF outline page (1-based)
    href: str | None = None  # EPUB href


@dataclass
class Section:
    """A structural unit provided directly by the source format (EPUB spine documents)."""

    title: str | None
    blocks: list[Block]
    source_ref: str | None = None


@dataclass
class DocMetadata:
    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    language: str | None = None
    publisher: str | None = None
    year: str | None = None
    description: str | None = None
    genre: str | None = None


@dataclass
class OcrReport:
    engine: str
    pages_ocrd: int = 0
    mean_confidence: float | None = None
    low_confidence_pages: list[int] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    format: str
    metadata: DocMetadata = field(default_factory=DocMetadata)
    blocks: list[Block] = field(default_factory=list)
    sections: list[Section] | None = None
    toc: list[TocEntry] = field(default_factory=list)
    page_count: int | None = None
    cover_image: bytes | None = None
    cover_mime: str | None = None
    ocr: OcrReport | None = None
    warnings: list[str] = field(default_factory=list)

    def all_blocks(self) -> list[Block]:
        if self.sections is not None:
            return [b for s in self.sections for b in s.blocks]
        return self.blocks


# progress(stage_message, fraction 0..1 or None when unknown)
ProgressCallback = Callable[[str, "float | None"], None]
