"""EasyOCR (PyTorch). Optional: `pip install easyocr` (large download, GPU helps)."""

from __future__ import annotations

import threading

from app.core.errors import ProviderError, ProviderUnavailableError
from app.providers.ocr.base import OCRProvider, OcrLine, OcrPage

EASYOCR_LANGS = {"en", "hi", "te", "ta", "kn", "bn", "mr", "ne", "ur", "ar", "fr", "de", "es", "it", "pt", "ru", "ja", "ko"}


class EasyOCRProvider(OCRProvider):
    name = "easyocr"
    supported_languages = EASYOCR_LANGS

    def __init__(self) -> None:
        self._readers: dict[tuple[str, ...], object] = {}
        self._lock = threading.Lock()

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import easyocr  # noqa: F401
        except ImportError:
            return False, "easyocr package not installed (pip install easyocr)."
        return True, None

    def recognize(self, image_png: bytes, languages: list[str] | None = None) -> OcrPage:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "EasyOCR unavailable", retryable=False)
        import easyocr

        langs = tuple(sorted({l for l in (languages or ["en"]) if l in EASYOCR_LANGS} | {"en"}))
        with self._lock:
            if langs not in self._readers:
                self._readers[langs] = easyocr.Reader(list(langs), gpu=False, verbose=False)
            reader = self._readers[langs]
        try:
            results = reader.readtext(image_png, paragraph=False)  # type: ignore[attr-defined]
        except Exception as exc:
            raise ProviderError(self.name, f"EasyOCR failed on this page: {exc}") from exc
        page = OcrPage(engine=self.name)
        for box, text, conf in results:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            page.lines.append(OcrLine(text=text, bbox=(min(xs), min(ys), max(xs), max(ys)), confidence=float(conf)))
        return page
