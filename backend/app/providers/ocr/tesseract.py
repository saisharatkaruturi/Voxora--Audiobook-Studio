"""Tesseract OCR (best language coverage, incl. all major Indic scripts).

Requires the Tesseract binary: https://github.com/UB-Mannheim/tesseract/wiki (Windows),
`apt install tesseract-ocr tesseract-ocr-tel tesseract-ocr-hin ...` (Linux),
`brew install tesseract tesseract-lang` (macOS).
"""

from __future__ import annotations

import io
import shutil
import threading
from pathlib import Path

from app.core.errors import ProviderError, ProviderUnavailableError
from app.providers.ocr.base import OCRProvider, OcrLine, OcrPage

# ISO 639-1 -> tesseract traineddata code
ISO_TO_TESS = {
    "en": "eng", "hi": "hin", "te": "tel", "ta": "tam", "kn": "kan", "ml": "mal", "bn": "ben", "mr": "mar",
    "gu": "guj", "pa": "pan", "or": "ori", "ur": "urd", "sa": "san", "ne": "nep", "fr": "fra", "de": "deu",
    "es": "spa", "it": "ita", "pt": "por", "ru": "rus", "ar": "ara", "zh": "chi_sim", "ja": "jpn", "ko": "kor",
}
_WINDOWS_PATHS = [Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"), Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")]


class TesseractOCR(OCRProvider):
    name = "tesseract"

    def __init__(self, cmd: str | None = None):
        self.cmd = cmd or shutil.which("tesseract") or next((str(p) for p in _WINDOWS_PATHS if p.exists()), None)
        self._langs: set[str] | None = None
        self._lock = threading.Lock()

    def _installed(self) -> set[str]:
        if self._langs is None:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = self.cmd
            try:
                self._langs = set(pytesseract.get_languages(config=""))
            except Exception:
                self._langs = set()
        return self._langs

    @property
    def supported_languages(self) -> set[str]:  # type: ignore[override]
        if not self.cmd:
            return set()
        installed = self._installed()
        return {iso for iso, code in ISO_TO_TESS.items() if code in installed}

    def is_available(self) -> tuple[bool, str | None]:
        if not self.cmd:
            return False, "Tesseract binary not found. Install it or set TESSERACT_CMD."
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False, "pytesseract package not installed."
        return True, None

    def recognize(self, image_png: bytes, languages: list[str] | None = None) -> OcrPage:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "Tesseract unavailable", retryable=False)
        import pytesseract
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = self.cmd
        installed = self._installed()
        codes = [ISO_TO_TESS[l] for l in (languages or ["en"]) if ISO_TO_TESS.get(l) in installed]
        lang = "+".join(dict.fromkeys(codes)) or ("eng" if "eng" in installed else None)
        image = Image.open(io.BytesIO(image_png))
        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT, config="--psm 3")
        except Exception as exc:
            raise ProviderError(self.name, f"Tesseract failed on this page: {exc}") from exc

        # Group words into lines keyed by (block, paragraph, line)
        lines: dict[tuple[int, int, int], list[int]] = {}
        for i, word in enumerate(data["text"]):
            if word and word.strip():
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                lines.setdefault(key, []).append(i)
        page = OcrPage(width=image.width, height=image.height, engine=self.name)
        for (block, par, _line), idxs in sorted(lines.items()):
            words = [data["text"][i] for i in idxs]
            confs = [float(data["conf"][i]) for i in idxs if float(data["conf"][i]) >= 0]
            x0 = min(data["left"][i] for i in idxs)
            y0 = min(data["top"][i] for i in idxs)
            x1 = max(data["left"][i] + data["width"][i] for i in idxs)
            y1 = max(data["top"][i] + data["height"][i] for i in idxs)
            page.lines.append(
                OcrLine(
                    text=" ".join(words),
                    bbox=(x0, y0, x1, y1),
                    confidence=(sum(confs) / len(confs) / 100) if confs else None,
                    block_id=block * 1000 + par,
                )
            )
        return page
