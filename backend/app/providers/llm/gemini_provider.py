"""Google Gemini via the Generative Language REST API. CLOUD provider.

Configure with GEMINI_API_KEY (or LLM_API_KEY). GEMINI_MODEL=auto picks the
newest available "Flash" model from the account's model list (fast and strong
for grounded Q&A); set a specific model id to pin one.
"""

from __future__ import annotations

import re
import threading
import time

import httpx

from app.core.errors import ProviderError, ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.llm.base import ChatMessage, LLMProvider

API = "https://generativelanguage.googleapis.com/v1beta"


def _version(name: str) -> tuple:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return (float(m.group(1)) if m else 0.0,)


class GeminiLLM(LLMProvider):
    name = "gemini"
    is_local = False
    privacy_note = "Book excerpts relevant to your request are sent to Google's Gemini API."

    def __init__(self, model: str, api_key: str | None, timeout: int = 120):
        super().__init__(model)
        self.api_key = api_key
        self.timeout = timeout
        self._resolved: str | None = None if model == "auto" else model
        self._fallbacks: list[str] = []
        self._cooldown: dict[str, float] = {}  # model -> time until which we skip it (overloaded)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ model selection
    def _pick_model(self) -> str:
        with self._lock:
            if self._resolved:
                return self._resolved
            try:
                resp = httpx.get(f"{API}/models", params={"pageSize": 200}, headers={"x-goog-api-key": self.api_key or ""}, timeout=15)
                resp.raise_for_status()
                models = [
                    m["name"].removeprefix("models/")
                    for m in resp.json().get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
            except httpx.HTTPError:
                models = []
            flash = [
                m for m in models
                if re.fullmatch(r"gemini-\d+(\.\d+)?-flash(-latest)?", m)  # stable Flash, not lite/preview/tts/image
            ]
            pool = flash or [m for m in models if "flash" in m and "lite" not in m and "tts" not in m and "image" not in m] or models
            self._resolved = max(pool, key=_version) if pool else "gemini-flash-latest"
            # Fallbacks when the preferred model is overloaded: other Flash models, newest first, then Flash-Lite.
            others = sorted({m for m in models if "flash" in m and not any(x in m for x in ("tts", "image", "audio", "live"))} - {self._resolved}, key=lambda m: ("lite" in m, [-v for v in _version(m)]))
            # Keep some Flash-Lite models in reach: they have separate (larger) free quotas,
            # so they still answer when the Flash models' daily quota is used up.
            self._fallbacks = [m for m in others if "lite" not in m][:3] + [m for m in others if "lite" in m][:3]
            self.model = self._resolved
            return self._resolved

    def is_available(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "Set GEMINI_API_KEY to use Gemini."
        self._pick_model()
        return True, None

    def describe(self) -> dict:
        info = super().describe()
        info["model"] = self._resolved or self.model
        return info

    # ------------------------------------------------------------------ generation
    def complete(self, system: str, messages: list[ChatMessage], *, max_tokens: int = 2000, json_schema: dict | None = None, prefer_fast: bool = False) -> str:
        """`prefer_fast`: for interactive requests (the search bar), try the Flash-Lite
        models first with a shorter timeout; they answer in seconds, not minutes."""
        if not self.api_key:
            raise ProviderUnavailableError(self.name, "Set GEMINI_API_KEY to use Gemini.", retryable=False)
        model = self._pick_model()
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]} for m in messages],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max(max_tokens, 1024)},
        }
        if json_schema is not None:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseJsonSchema"] = json_schema
        now = time.monotonic()
        chain = [model, *self._fallbacks]
        if prefer_fast:
            chain = [m for m in chain if "lite" in m and "preview" not in m] + [m for m in chain if "lite" not in m or "preview" in m]
        order = [m for m in chain if self._cooldown.get(m, 0) <= now] or [model]
        timeout = min(self.timeout, 30) if prefer_fast else self.timeout
        resp = None
        for candidate in order:
            try:
                resp = self._post(candidate, body, timeout)
            except ProviderTimeoutError:
                if not prefer_fast or candidate == order[-1]:
                    raise
                self._cooldown[candidate] = time.monotonic() + 120
                continue
            if resp.status_code not in (429, 500, 503, 404):
                break
            # Overloaded / unavailable: skip this model for a while and try the next-best Flash model.
            self._cooldown[candidate] = time.monotonic() + (600 if resp.status_code == 404 else 120)
        if resp.status_code == 400 and json_schema is not None and "responseJsonSchema" in resp.text:
            # Older API revisions: keep JSON mode, describe the schema in the prompt instead.
            body["generationConfig"].pop("responseJsonSchema", None)
            body["contents"][-1]["parts"][0]["text"] += f"\n\nRespond with JSON matching this schema: {json_schema}"
            resp = self._post(model, body)
        if resp.status_code == 429:
            raise ProviderRateLimitError(self.name, "Gemini rate limit reached. Try again in a moment.")
        if resp.status_code in (401, 403):
            raise ProviderError(self.name, "Gemini rejected the API key. Check GEMINI_API_KEY.", retryable=False)
        if resp.status_code >= 400:
            detail = resp.json().get("error", {}).get("message", resp.text[:200]) if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
            raise ProviderError(self.name, f"Gemini API error {resp.status_code}: {detail}", retryable=resp.status_code >= 500)
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = data.get("promptFeedback", {}).get("blockReason", "no answer returned")
            raise ProviderError(self.name, f"Gemini returned no answer ({reason}).", retryable=False, code="llm_refusal")
        parts = candidates[0].get("content", {}).get("parts", [])
        # Skip any "thought" parts some models return; keep the answer text.
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def _post(self, model: str, body: dict, timeout: float | None = None) -> httpx.Response:
        self.last_model = model
        for attempt in range(2):
            try:
                resp = httpx.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": self.api_key or ""}, json=body, timeout=timeout or self.timeout)
            except httpx.TimeoutException as exc:
                if attempt == 1:
                    raise ProviderTimeoutError(self.name, "Gemini took too long to respond.") from exc
            except httpx.HTTPError as exc:
                if attempt == 1:
                    raise ProviderUnavailableError(self.name, f"Could not reach Gemini: {exc}") from exc
            else:
                if resp.status_code not in (429, 500, 502, 503, 504) or attempt == 1:
                    return resp
            time.sleep(1.5)  # brief retry, then the caller falls back to another model
        raise ProviderUnavailableError(self.name, "Could not reach Gemini.")
