"""Extraction + structure detection on the synthetic public-domain sample book in every format."""

import pytest

from app.document_processing.pipeline import AnalyzeOptions, analyze
from app.providers.ocr import list_ocr_providers
from tests.conftest import FIXTURES

EXPECTED_CHAPTERS = ["Chapter 1: The Keeper", "Chapter 2: The Letter", "Chapter 3: The Signal", "Chapter 4: The Long Night"]


def _analyze(name: str, fmt: str, **opts):
    return analyze(FIXTURES / name, fmt, name, AnalyzeOptions(**opts))


def _titles(result) -> list[str]:
    return [c.title for c in result.structure.chapters]


@pytest.mark.parametrize("name,fmt", [("lantern-at-gull-point.txt", "txt"), ("lantern-at-gull-point.pdf", "pdf"), ("lantern-at-gull-point.docx", "docx"), ("lantern-at-gull-point.epub", "epub")])
def test_extracts_chapters_in_order(name, fmt):
    result = _analyze(name, fmt)
    titles = _titles(result)
    positions = [next(i for i, t in enumerate(titles) if t.lower() == want.lower()) for want in EXPECTED_CHAPTERS]
    assert positions == sorted(positions), titles
    assert result.structure.title.lower() == "the lantern at gull point"
    assert result.primary_language == "en"


@pytest.mark.parametrize("name,fmt", [("lantern-at-gull-point.pdf", "pdf"), ("lantern-at-gull-point.txt", "txt")])
def test_front_matter_is_classified_and_not_narrated(name, fmt):
    chapters = _analyze(name, fmt).structure.chapters
    kinds = {c.title: (c.kind, c.include_in_audio) for c in chapters}
    toc = [v for t, v in kinds.items() if t.lower() in ("contents", "table of contents")]
    assert toc and toc[0] == ("toc", False)
    epilogue = [v for t, v in kinds.items() if t.lower() == "epilogue"]
    assert epilogue and epilogue[0][0] == "epilogue" and epilogue[0][1]


def test_pdf_text_is_clean_prose():
    result = _analyze("lantern-at-gull-point.pdf", "pdf")
    ch1 = next(c for c in result.structure.chapters if c.title == "Chapter 1: The Keeper")
    text = " ".join(b.text for b in ch1.blocks)
    assert "ninety-seven steps" in text
    assert "\n" not in text  # wrapped lines were joined
    assert result.document.ocr is None or result.document.ocr.pages_ocrd == 0  # real text layer, no OCR


def test_numbered_paragraphs_are_not_chapters():
    result = _analyze("lantern-at-gull-point.txt", "txt")
    assert len(result.structure.chapters) < 15


@pytest.mark.skipif(not any(p.is_available()[0] for p in list_ocr_providers()), reason="no OCR engine installed")
def test_scanned_pdf_is_detected_and_ocrd_automatically():
    result = _analyze("lantern-at-gull-point-scanned.pdf", "pdf")
    assert result.document.ocr is not None and result.document.ocr.pages_ocrd > 0
    assert result.document.ocr.mean_confidence is None or result.document.ocr.mean_confidence > 0.5
    text = " ".join(b.text for c in result.structure.chapters for b in c.blocks).lower()
    assert "lantern" in text and "mara" in text
    assert any("keeper" in t.lower() for t in _titles(result))
