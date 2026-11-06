"""Anthropic Claude via the official `anthropic` SDK. CLOUD provider.

Credentials resolve like every Anthropic SDK client: LLM_API_KEY if set, else
ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile.
Server-side refusal fallbacks are enabled (`fallbacks="default"`).
"""

from __future__ import annotations

from app.core.errors import ProviderError, ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError
from app.providers.llm.base import ChatMessage, LLMProvider

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(LLMProvider):
    name = "anthropic"
    is_local = False
    privacy_note = "Book excerpts relevant to your request are sent to Anthropic's API."

    def __init__(self, model: str, api_key: str | None, timeout: int = 180):
        super().__init__(model)
        self.api_key = api_key
        self.timeout = timeout
        self._client = None

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "The 'anthropic' package is not installed (pip install anthropic)."
        return True, None

    def _get_client(self):
        import anthropic

        if self._client is None:
            kwargs = {"timeout": self.timeout, "max_retries": 3}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def complete(self, system: str, messages: list[ChatMessage], *, max_tokens: int = 2000, json_schema: dict | None = None) -> str:
        import anthropic

        params: dict = {
            "model": self.model,
            "max_tokens": max(max_tokens, 4000),
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "medium"},
        }
        if json_schema is not None:
            params["output_config"]["format"] = {"type": "json_schema", "schema": _strict(json_schema)}
        try:
            response = self._get_client().beta.messages.create(**params)
        except anthropic.AuthenticationError as exc:
            raise ProviderError(self.name, "Anthropic rejected the credentials. Check LLM_API_KEY or ANTHROPIC_API_KEY.", retryable=False) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimitError(self.name, "Anthropic rate limit reached. Try again shortly.") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError(self.name, "Anthropic's API timed out.") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailableError(self.name, f"Could not reach Anthropic's API: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(self.name, f"Anthropic API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500) from exc
        if response.stop_reason == "refusal":
            raise ProviderError(self.name, "The model declined this request.", retryable=False, code="llm_refusal")
        return "".join(block.text for block in response.content if block.type == "text")


def _strict(schema: dict) -> dict:
    """Structured outputs require additionalProperties=false and full `required` on objects."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object" and "properties" in out:
        out["properties"] = {k: _strict(v) for k, v in out["properties"].items()}
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    if out.get("type") == "array" and "items" in out:
        out["items"] = _strict(out["items"])
    return out
