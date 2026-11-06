"""Local LLM via Ollama (https://ollama.com). Nothing leaves the machine."""

from __future__ import annotations

import httpx

from app.core.errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.llm.base import ChatMessage, LLMProvider


class OllamaLLM(LLMProvider):
    name = "ollama"
    is_local = True
    privacy_note = "Runs on this computer through Ollama. Book text never leaves your machine."

    def __init__(self, model: str, base_url: str, timeout: int = 180):
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auto = model == "auto"
        self._resolve()

    def _resolve(self) -> None:
        """OLLAMA_MODEL=auto: pick the best installed model, re-checking until one is found
        (Ollama may be busy or starting when the app boots)."""
        if self.auto and (self.model == "auto" or not self._installed(self.model)):
            self.model = best_local_model(self.base_url) or "auto"
        self.is_local = not (self.model.endswith(":cloud") or "-cloud" in self.model)
        if not self.is_local:
            self.privacy_note = "This Ollama model runs on Ollama's cloud: relevant book excerpts are sent to Ollama's servers."

    def _installed(self, model: str) -> bool:
        try:
            names = {m.get("name") for m in httpx.get(f"{self.base_url}/api/tags", timeout=10).json().get("models", [])}
        except httpx.HTTPError:
            return False
        return model in names or f"{model}:latest" in names

    def is_available(self) -> tuple[bool, str | None]:
        if self.auto and self.model == "auto":
            self._resolve()
            if self.model == "auto":
                return False, "No local chat model found in Ollama. Run `ollama pull llama3.1:8b` (or set ANTHROPIC_API_KEY)."
        try:
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            resp.raise_for_status()
        except httpx.HTTPError:
            return False, f"Ollama is not running at {self.base_url}. Start it with `ollama serve`."
        names = {m.get("name") for m in resp.json().get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            return False, f"Ollama model '{self.model}' is not pulled. Run `ollama pull {self.model}`."
        return True, None

    def complete(self, system: str, messages: list[ChatMessage], *, max_tokens: int = 2000, json_schema: dict | None = None) -> str:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
            "keep_alive": "30m",  # keep the model warm between questions
        }
        if json_schema is not None:
            body["format"] = json_schema
        if _thinks(self.model):
            # Reasoning models spend minutes "thinking" on CPU; grounded answers don't need it.
            body["think"] = False
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.name, f"Ollama ({self.model}) timed out. Large models can be slow on CPU.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Could not reach Ollama at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"Ollama error {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("message", {}).get("content", "")


_THINKING = ("qwen3", "qwen3.5", "deepseek-r1", "magistral", "gpt-oss")


def _thinks(model: str) -> bool:
    return model.split(":")[0] in _THINKING


# Good, responsive chat models first (answers must come back in reasonable time on a CPU);
# coding-only and cloud-hosted models are never auto-picked.
_PREFERENCE = ["gemma3", "llama3.1", "qwen2.5", "gemma2", "mistral", "llama3.2", "qwen3.5", "qwen3", "llama3.3", "mistral-small", "llama3", "phi4", "phi3"]


def best_local_model(base_url: str) -> str | None:
    """Pick the best installed local chat model (LLM_PROVIDER=auto / OLLAMA_MODEL=auto)."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    local = [n for n in names if not n.endswith(":cloud") and "-cloud" not in n and not any(x in n for x in ("coder", "embed", "vision", "code"))]
    for family in _PREFERENCE:
        for n in local:
            if n.split(":")[0] == family:
                return n
    return local[0] if local else None
