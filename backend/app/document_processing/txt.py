"""Plain-text extraction with encoding detection and Project Gutenberg support."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import CorruptedFileError
from app.document_processing.base import Block, DocMetadata, ExtractedDocument, ProgressCallback
from app.document_processing.cleaning import split_plain_paragraphs

_GUTENBERG_START = re.compile(r"\*{3}\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*?\*{3}", re.I)
_GUTENBERG_END = re.compile(r"\*{3}\s*END OF (?:THE|THIS) PROJECT GUTENBERG", re.I)


def decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # optional, installed with many packages

        best = from_bytes(raw[:200_000]).best()
        if best is not None:
            return raw.decode(best.encoding, errors="replace")
    except ImportError:
        pass
    return raw.decode("cp1252", errors="replace")


def _split_title_lists(paragraphs: list[str]) -> list[str]:
    """A paragraph whose lines are mostly chapter titles (a contents list) is split
    into one paragraph per line, so each title can be recognised."""
    from app.document_processing.structure import DOT_LEADER, PART, SPECIAL, STRONG_CHAPTER

    out: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        titled = sum(1 for ln in lines if STRONG_CHAPTER.match(ln) or PART.match(ln) or SPECIAL.match(ln) or DOT_LEADER.search(ln))
        if len(lines) >= 3 and titled / len(lines) >= 0.6 and max(len(ln) for ln in lines) < 100:
            out.extend(lines)
        else:
            out.append(para)
    return out


class TxtExtractor:
    def extract(self, path: Path, progress: ProgressCallback | None = None) -> ExtractedDocument:
        raw = path.read_bytes()
        if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise CorruptedFileError("This file looks binary, not plain text.")
        text = decode_text(raw)
        meta = DocMetadata()

        # Project Gutenberg: take metadata from the header and drop the license boilerplate.
        head = text[:6000]
        if m := re.search(r"^Title:\s*(.+)$", head, re.M):
            meta.title = m.group(1).strip()
        if m := re.search(r"^Author:\s*(.+)$", head, re.M):
            meta.author = m.group(1).strip()
        if m := re.search(r"^Language:\s*(.+)$", head, re.M):
            lang = m.group(1).strip().lower()
            meta.language = {"english": "en", "hindi": "hi", "telugu": "te", "tamil": "ta", "french": "fr", "german": "de"}.get(lang)
        if start := _GUTENBERG_START.search(text):
            text = text[start.end():]
        if end := _GUTENBERG_END.search(text):
            text = text[: end.start()]

        blocks = []
        for para in _split_title_lists(split_plain_paragraphs(text)):
            lines = para.strip().split("\n")
            # Short single-line paragraphs are heading *candidates*; structure detection decides.
            candidate = len(lines) == 1 and len(lines[0].strip()) < 90 and not lines[0].strip().endswith((".", ",", ";"))
            blocks.append(Block(text=para.strip(), meta={"heading_candidate": candidate}))
        return ExtractedDocument(format="txt", metadata=meta, blocks=blocks)
