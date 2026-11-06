"""OpenAI-compatible chat completions (OpenAI, OpenRouter, LM Studio, vLLM...). CLOUD unless pointed at a local server."""

from __future__ import annotations

import httpx

from app.core.errors import ProviderError, ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.llm.base import ChatMessage, LLMProvider


class OpenAICompatibleLLM(LLMProvider):
    name = "openai"
    is_local = False
    privacy_note = "Book excerpts relevant to your question are sent to the configured OpenAI-compatible API."

    def __init__(self, model: str, api_key: str | None, base_url: str | None, timeout: int = 180):
        super().__init__(model)
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        self.is_local = self.base_url.startswith(("http://localhost", "http://127.0.0.1"))

    def is_available(self) -> tuple[bool, str | None]:
        if not self.api_key and not self.is_local:
            return False, "Set LLM_API_KEY to use the OpenAI-compatible provider."
        return True, None

    def complete(self, system: str, messages: list[ChatMessage], *, max_tokens: int = 2000, json_schema: dict | None = None) -> str:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": json_schema}}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.name, "The LLM API timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.name, f"Could not reach the LLM API: {exc}") from exc
        if resp.status_code == 429:
            raise ProviderRateLimitError(self.name, "LLM API rate limit reached. Try again shortly.")
        if resp.status_code in (401, 403):
            raise ProviderError(self.name, "The LLM API rejected the API key. Check LLM_API_KEY.", retryable=False)
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"LLM API error {resp.status_code}: {resp.text[:200]}", retryable=resp.status_code >= 500)
        return resp.json()["choices"][0]["message"].get("content") or ""
