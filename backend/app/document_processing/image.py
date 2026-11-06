"""Single page images (JPG/PNG/WebP/TIFF, incl. multi-page TIFF) via OCR."""

from __future__ import annotations

import io
from pathlib import Path

from app.core.errors import CorruptedFileError
from app.document_processing.base import ExtractedDocument, OcrReport, ProgressCallback
from app.document_processing.ocr_layout import ocr_page_to_blocks


class ImageExtractor:
    def __init__(self, languages: list[str] | None = None, ocr_provider: str | None = None):
        self.languages = languages or ["en"]
        self.ocr_provider_name = ocr_provider

    def extract(self, path: Path, progress: ProgressCallback | None = None) -> ExtractedDocument:
        from PIL import Image, ImageOps, UnidentifiedImageError

        from app.providers.ocr import get_ocr_provider

        try:
            img = Image.open(path)
        except (UnidentifiedImageError, OSError) as exc:
            raise CorruptedFileError("This image could not be opened. It may be corrupted.") from exc
        provider = get_ocr_provider(self.ocr_provider_name, self.languages)
        result = ExtractedDocument(format="image")
        report = OcrReport(engine=provider.name)
        frames = getattr(img, "n_frames", 1)
        confs: list[float] = []
        for i in range(frames):
            img.seek(i)
            if progress:
                progress(f"Running OCR on image page {i + 1} of {frames}", i / frames)
            frame = ImageOps.exif_transpose(img.convert("L"))
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            page = provider.recognize(buf.getvalue(), self.languages)
            result.blocks.extend(ocr_page_to_blocks(page, i + 1))
            report.pages_ocrd += 1
            if page.mean_confidence is not None:
                confs.append(page.mean_confidence)
                if page.mean_confidence < 0.7:
                    report.low_confidence_pages.append(i + 1)
        report.mean_confidence = sum(confs) / len(confs) if confs else None
        result.ocr = report
        result.page_count = frames
        return result
