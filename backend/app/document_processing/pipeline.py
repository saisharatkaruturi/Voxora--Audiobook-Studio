"""Document pipeline: extract -> clean -> detect languages -> detect structure."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.document_processing.base import Block, ExtractedDocument, ProgressCallback
from app.document_processing.cleaning import clean_blocks
from app.document_processing.detect import IMAGE_FORMATS
from app.document_processing.language import detect_language, summarize_languages
from app.document_processing.structure import BookStructure, detect_structure


@dataclass
class AnalyzeOptions:
    ocr_mode: str = "auto"  # auto | force | off
    languages: list[str] = field(default_factory=list)  # hint for OCR / detection; empty = auto
    ocr_provider: str | None = None
    ocr_dpi: int = 300
    max_pages: int = 5000


@dataclass
class AnalysisResult:
    document: ExtractedDocument
    structure: BookStructure
    primary_language: str | None
    languages: list[str]


def extract(path: Path, fmt: str, options: AnalyzeOptions, progress: ProgressCallback | None = None) -> ExtractedDocument:
    langs = options.languages or ["en"]
    if fmt == "pdf":
        from app.document_processing.pdf import PdfExtractor

        return PdfExtractor(options.ocr_mode, langs, options.ocr_provider, options.ocr_dpi, options.max_pages).extract(path, progress)
    if fmt == "docx":
        from app.document_processing.docx_extractor import DocxExtractor

        return DocxExtractor().extract(path, progress)
    if fmt == "epub":
        from app.document_processing.epub import EpubExtractor

        return EpubExtractor().extract(path, progress)
    if fmt == "txt":
        from app.document_processing.txt import TxtExtractor

        return TxtExtractor().extract(path, progress)
    if fmt in IMAGE_FORMATS:
        from app.document_processing.image import ImageExtractor

        return ImageExtractor(langs, options.ocr_provider).extract(path, progress)
    raise ValueError(f"No extractor for format {fmt!r}")


def clean(doc: ExtractedDocument) -> None:
    ocr = doc.ocr is not None and doc.ocr.pages_ocrd > 0
    if doc.sections is not None:
        for section in doc.sections:
            section.blocks = clean_blocks(section.blocks, ocr=ocr, remove_page_numbers=False)
        doc.sections = [s for s in doc.sections if s.blocks]
    else:
        doc.blocks = clean_blocks(doc.blocks, ocr=ocr)


def tag_languages(blocks: list[Block], hint: str | None) -> tuple[str | None, list[str]]:
    counts: Counter[str] = Counter()
    last = hint
    for b in blocks:
        lang = detect_language(b.text, default=last)
        b.meta["language"] = lang
        if lang:
            counts[lang] += len(b.text)
            last = lang
    langs = summarize_languages(counts)
    primary = langs[0] if langs else hint
    # Short paragraphs inherited a neighbour's language; re-default them to the primary.
    for b in blocks:
        if not b.meta.get("language"):
            b.meta["language"] = primary
    return primary, langs


def _title_from_first_page(doc: ExtractedDocument) -> str | None:
    """The most prominent text on page 1 (title pages repeat the title in running
    headers, which cleaning removes, so capture it before cleaning)."""
    first = [b for b in doc.blocks if b.page == 1 and b.font_size and not b.meta.get("edge") and len(b.text) < 120]
    sizes = [b.font_size for b in doc.blocks[:300] if b.font_size]
    if not first or not sizes:
        return None
    top = max(first, key=lambda b: b.font_size or 0)
    body = sorted(sizes)[len(sizes) // 2]
    if (top.font_size or 0) >= body * 1.5:
        return " ".join(top.text.split())
    return None


def analyze(path: Path, fmt: str, filename: str, options: AnalyzeOptions, progress: ProgressCallback | None = None) -> AnalysisResult:
    doc = extract(path, fmt, options, progress)
    if not doc.metadata.title and doc.sections is None:
        doc.metadata.title = _title_from_first_page(doc)
    if progress:
        progress("Cleaning text", None)
    clean(doc)
    if progress:
        progress("Detecting languages", None)
    hint = (options.languages[0] if options.languages else None) or doc.metadata.language
    primary, langs = tag_languages(doc.all_blocks(), hint)
    if progress:
        progress("Detecting chapters", None)
    structure = detect_structure(doc, filename)
    return AnalysisResult(document=doc, structure=structure, primary_language=primary, languages=langs)
