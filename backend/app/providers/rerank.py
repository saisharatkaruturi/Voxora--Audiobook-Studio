"""Cross-encoder reranking for Ask the Book.

Hybrid retrieval (dense vectors + BM25) finds candidates quickly; a cross-encoder
then reads each (question, passage) pair together and reorders them, which is
markedly more accurate for "who / why" questions. Runs locally (ONNX via fastembed).
If the model can't load, retrieval silently keeps the hybrid order.
"""

from __future__ import annotations

import threading
from functools import lru_cache

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class Reranker:
    def __init__(self, model: str, cache_dir: str):
        self.model = model
        self.cache_dir = cache_dir
        self._impl = None
        self._failed = False
        self._lock = threading.Lock()

    def score(self, query: str, passages: list[str]) -> np.ndarray | None:
        with self._lock:
            if self._failed:
                return None
            if self._impl is None:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    self._impl = TextCrossEncoder(model_name=self.model, cache_dir=self.cache_dir)
                except Exception as exc:  # missing package, offline download, ...
                    self._failed = True
                    log.warning("rerank.unavailable", model=self.model, error=str(exc)[:200])
                    return None
            impl = self._impl
        try:
            return np.array(list(impl.rerank(query, passages)), dtype=np.float32)
        except Exception as exc:
            log.warning("rerank.failed", model=self.model, error=str(exc)[:200])
            return None


@lru_cache
def get_reranker(language: str | None) -> Reranker | None:
    s = get_settings()
    if not s.rerank_enabled or s.embedding_provider == "hashing":
        return None
    model = s.rerank_model_en if language in (None, "", "en") else s.rerank_model_multilingual
    return Reranker(model, str(s.fastembed_cache_path))
