"""RapidOCR (PaddleOCR models on ONNX Runtime). Pure pip install, no system binaries.

The bundled recognizer reads Latin script (English) and Chinese. Telugu, Tamil,
Devanagari (Hindi/Marathi), Arabic, Cyrillic, Korean, Japanese, Greek and Thai
recognizers are downloaded on first use.
"""

from __future__ import annotations

import os
import queue
import threading

from app.core.config import get_settings
from app.core.errors import ProviderError, ProviderUnavailableError
from app.providers.ocr.base import OCRProvider, OcrLine, OcrPage

# ISO 639-1 -> RapidOCR recognizer family
ISO_TO_REC = {
    "en": "en", "zh": "ch", "te": "te", "ta": "ta", "hi": "devanagari", "mr": "devanagari", "ne": "devanagari",
    "sa": "devanagari", "ar": "arabic", "ur": "arabic", "fa": "arabic", "ru": "cyrillic", "uk": "cyrillic",
    "ko": "korean", "ja": "japan", "el": "el", "th": "th", "ka": "ka",
    "fr": "latin", "de": "latin", "es": "latin", "it": "latin", "pt": "latin", "nl": "latin",
}


class RapidOCRProvider(OCRProvider):
    name = "rapidocr"
    supported_languages = set(ISO_TO_REC)

    def __init__(self) -> None:
        # Engines are pooled per recognizer (OCR_PARALLEL_PAGES pages at once). The
        # default is one: on a 12-thread laptop CPU three engines measured only 1.17x
        # faster, for triple the memory; recognition is the bottleneck, not idle cores.
        cores = os.cpu_count() or 4
        self.max_parallel_pages = max(1, get_settings().ocr_parallel_pages)
        self._threads = max(2, min(8, cores // (2 * self.max_parallel_pages)))
        self._pools: dict[str, queue.Queue] = {}
        self._created: dict[str, int] = {}
        self._lock = threading.Lock()

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            return False, "rapidocr package not installed (pip install rapidocr onnxruntime)."
        return True, None

    def _acquire(self, rec: str):
        with self._lock:
            pool = self._pools.setdefault(rec, queue.Queue())
            try:
                return pool.get_nowait()
            except queue.Empty:
                pass
            if self._created.get(rec, 0) < self.max_parallel_pages:
                self._created[rec] = self._created.get(rec, 0) + 1
                try:
                    return self._new_engine(rec)
                except Exception:
                    self._created[rec] -= 1
                    raise
        return pool.get()

    def _new_engine(self, rec: str):
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

        from app.core.config import get_settings

        low_mem = get_settings().ocr_low_memory

        params = {
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.intra_op_num_threads": 1 if low_mem else self._threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": not low_mem,
            # PP-OCRv5 mobile models: markedly faster on CPU than v6 "small", same accuracy on book pages.
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec(rec),
        }
        try:
            return RapidOCR(params=params)
        except Exception as exc:
            raise ProviderUnavailableError(
                self.name, f"Could not load the RapidOCR '{rec}' recognizer: {exc}", retryable=False
            ) from exc

    def recognize(self, image_png: bytes, languages: list[str] | None = None) -> OcrPage:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "RapidOCR unavailable", retryable=False)
        langs = languages or ["en"]
        # Non-Latin scripts need their own recognizer; the default 'ch' model reads Latin + Chinese well.
        rec = next((ISO_TO_REC[l] for l in langs if ISO_TO_REC.get(l) not in (None, "en", "latin", "ch")), None)
        if rec is None:
            rec = "ch" if "zh" in langs else ("latin" if any(ISO_TO_REC.get(l) == "latin" for l in langs) else "en")
        engine = self._acquire(rec)
        try:
            out = engine(image_png, use_cls=False)
        except Exception as exc:
            raise ProviderError(self.name, f"RapidOCR failed on this page: {exc}") from exc
        finally:
            self._pools[rec].put(engine)
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(image_png))
        page = OcrPage(width=img.width, height=img.height, engine=f"{self.name}:{rec}")
        boxes = getattr(out, "boxes", None)
        txts = getattr(out, "txts", None)
        scores = getattr(out, "scores", None)
        if boxes is None or txts is None:
            return page
        for box, text, score in zip(boxes, txts, scores or [None] * len(txts)):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            page.lines.append(
                OcrLine(text=str(text), bbox=(min(xs), min(ys), max(xs), max(ys)), confidence=float(score) if score is not None else None)
            )
        return page

