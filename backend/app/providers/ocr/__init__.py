"""OCR provider registry.

OCR_PROVIDER=auto picks Tesseract when its binary is installed (widest language
coverage), otherwise RapidOCR (pip-only), otherwise EasyOCR.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import ProviderUnavailableError
from app.providers.ocr.base import OCRProvider, OcrLine, OcrPage


@lru_cache
def _instances() -> dict[str, OCRProvider]:
    from app.providers.ocr.easyocr_provider import EasyOCRProvider
    from app.providers.ocr.rapid import RapidOCRProvider
    from app.providers.ocr.tesseract import TesseractOCR

    return {
        "tesseract": TesseractOCR(get_settings().tesseract_cmd),
        "rapidocr": RapidOCRProvider(),
        "easyocr": EasyOCRProvider(),
    }


def list_ocr_providers() -> list[OCRProvider]:
    return list(_instances().values())


def get_ocr_provider(name: str | None = None, languages: list[str] | None = None) -> OCRProvider:
    name = (name or get_settings().ocr_provider).lower()
    if name == "none":
        # Small servers (e.g. Render's free 512 MB) switch OCR off: its models alone need ~400 MB.
        raise ProviderUnavailableError(
            "ocr",
            "Reading scanned pages isn't available on this server. Upload a PDF with selectable text, an EPUB or a Word file.",
            retryable=False,
        )
    providers = _instances()
    if name != "auto":
        provider = providers.get(name)
        if provider is None:
            raise ProviderUnavailableError(name, f"Unknown OCR provider '{name}'.", retryable=False)
        ok, reason = provider.is_available()
        if not ok:
            raise ProviderUnavailableError(name, reason or f"OCR provider '{name}' is unavailable.", retryable=False)
        return provider
    wanted = set(languages or ["en"])
    available = [p for p in providers.values() if p.is_available()[0]]
    if not available:
        raise ProviderUnavailableError(
            "ocr", "No OCR engine is installed. Install Tesseract, or run: pip install rapidocr onnxruntime", retryable=False
        )
    # Prefer an engine that covers every detected language, in priority order.
    for p in available:
        if wanted <= p.supported_languages:
            return p
    return available[0]


__all__ = ["OCRProvider", "OcrLine", "OcrPage", "get_ocr_provider", "list_ocr_providers"]
