"""Embedding providers.

- hashing:   zero-download lexical embeddings (feature hashing of words + char n-grams).
             Works offline in any language; weaker at paraphrase.
- fastembed: local ONNX sentence embeddings (downloads a model once, ~70-220 MB).
- ollama:    local embedding model served by Ollama (e.g. nomic-embed-text).
- openai:    OpenAI-compatible /embeddings API (cloud).

`auto` in the registry falls back to hashing if the configured provider fails,
so book indexing never blocks on a missing model.
"""

from __future__ import annotations

import hashlib
import re
import threading
from abc import ABC, abstractmethod
from functools import lru_cache

import numpy as np

from app.core.config import get_settings
from app.core.errors import ProviderError, ProviderUnavailableError


class EmbeddingProvider(ABC):
    name = "base"
    is_local = True

    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        """Return L2-normalized float32 vectors, shape (n, dim)."""


def _normalize(m: np.ndarray) -> np.ndarray:
    m = m.astype(np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return m / norms


class HashingEmbeddings(EmbeddingProvider):
    name = "hashing"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    @property
    def model_id(self) -> str:
        return f"hashing-{self.dim}"

    def _features(self, text: str) -> list[str]:
        text = text.lower()
        words = re.findall(r"\w+", text)
        feats = [f"w:{w}" for w in words]
        feats += [f"b:{a}_{b}" for a, b in zip(words, words[1:])]
        for w in words:
            padded = f"#{w}#"
            feats += [f"c:{padded[i:i + 4]}" for i in range(max(1, len(padded) - 3))]
        return feats

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for f in self._features(t):
                h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
                weight = 1.0 if f.startswith("w:") else 0.5 if f.startswith("b:") else 0.25
                out[i, h % self.dim] += weight if (h >> 63) & 1 else -weight
        return _normalize(out)


class FastEmbedEmbeddings(EmbeddingProvider):
    name = "fastembed"

    def __init__(self, model: str, cache_dir: str):
        self.model = model
        self.cache_dir = cache_dir
        self._impl = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return f"fastembed:{self.model}"

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        with self._lock:
            if self._impl is None:
                try:
                    from fastembed import TextEmbedding
                except ImportError as exc:
                    raise ProviderUnavailableError(self.name, "fastembed is not installed (pip install fastembed).", retryable=False) from exc
                try:
                    self._impl = TextEmbedding(model_name=self.model, cache_dir=self.cache_dir)
                except Exception as exc:
                    raise ProviderUnavailableError(self.name, f"Could not load embedding model {self.model}: {exc}") from exc
            impl = self._impl
        vectors = list(impl.query_embed(texts) if query else impl.embed(texts, batch_size=32))
        return _normalize(np.array(vectors))


class OllamaEmbeddings(EmbeddingProvider):
    name = "ollama"

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.base_url = base_url.rstrip("/")

    @property
    def model_id(self) -> str:
        return f"ollama:{self.model}"

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        import httpx

        try:
            resp = httpx.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}, timeout=120)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Ollama embeddings failed ({self.model}): {exc}") from exc
        return _normalize(np.array(resp.json()["embeddings"]))


class OpenAIEmbeddings(EmbeddingProvider):
    name = "openai"
    is_local = False

    def __init__(self, model: str, api_key: str | None, base_url: str | None):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    @property
    def model_id(self) -> str:
        return f"openai:{self.model}"

    def embed(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        import httpx

        if not self.api_key:
            raise ProviderUnavailableError(self.name, "Set LLM_API_KEY to use OpenAI embeddings.", retryable=False)
        resp = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model, "input": texts},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120,
        )
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"Embeddings API error {resp.status_code}: {resp.text[:200]}")
        return _normalize(np.array([d["embedding"] for d in resp.json()["data"]]))


def get_embedding_provider(name: str | None = None, language: str | None = None) -> EmbeddingProvider:
    """English books get an English-tuned model; every other language a multilingual one
    (an English-only model would silently break retrieval for Hindi, Telugu, ...)."""
    return _provider(name, "en" if language in (None, "", "en") else "mul")


def embedder_for(model_id: str) -> EmbeddingProvider:
    """The embedder that produced an index (queries must use the same model)."""
    kind, _, model = model_id.partition(":")
    s = get_settings()
    if kind == "fastembed" and model:
        return _fastembed(model)
    if kind == "ollama" and model:
        return OllamaEmbeddings(model, s.ollama_base_url)
    if kind == "openai" and model:
        return OpenAIEmbeddings(model, s.llm_api_key, s.llm_base_url)
    return HashingEmbeddings()


@lru_cache
def _fastembed(model: str) -> FastEmbedEmbeddings:
    return FastEmbedEmbeddings(model, str(get_settings().fastembed_cache_path))


@lru_cache
def _provider(name: str | None, lang_bucket: str) -> EmbeddingProvider:
    s = get_settings()
    name = (name or s.embedding_provider).lower()
    if name == "fastembed":
        return _fastembed(s.embedding_model or (s.embedding_model_en if lang_bucket == "en" else s.embedding_model_multilingual))
    if name == "ollama":
        return OllamaEmbeddings(s.embedding_model or "nomic-embed-text", s.ollama_base_url)
    if name == "openai":
        return OpenAIEmbeddings(s.embedding_model or "text-embedding-3-small", s.llm_api_key, s.llm_base_url)
    return HashingEmbeddings()


__all__ = ["EmbeddingProvider", "HashingEmbeddings", "embedder_for", "get_embedding_provider"]
