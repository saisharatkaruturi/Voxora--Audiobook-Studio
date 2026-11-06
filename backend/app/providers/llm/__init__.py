from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.providers.llm.base import ChatMessage, LLMProvider, parse_json


@lru_cache
def get_llm_provider() -> LLMProvider | None:
    """The configured LLM, or None when LLM_PROVIDER=none."""
    s = get_settings()
    name = s.llm_provider.lower()
    if name in ("none", "", "off"):
        return None
    if name == "auto":
        name = "gemini" if s.gemini_api_key else "anthropic" if _has_anthropic_credentials() else "ollama"
    if name == "gemini":
        from app.providers.llm.gemini_provider import GeminiLLM

        return GeminiLLM(s.llm_model or s.gemini_model, s.gemini_api_key or s.llm_api_key, s.llm_timeout_seconds)
    if name == "ollama":
        from app.providers.llm.ollama_provider import OllamaLLM

        return OllamaLLM(s.llm_model or s.ollama_model, s.llm_base_url or s.ollama_base_url, s.llm_timeout_seconds)
    if name == "openai":
        from app.providers.llm.openai_provider import OpenAICompatibleLLM

        return OpenAICompatibleLLM(s.llm_model or s.openai_llm_model, s.llm_api_key, s.llm_base_url, s.llm_timeout_seconds)
    if name == "anthropic":
        from app.providers.llm.anthropic_provider import AnthropicLLM

        return AnthropicLLM(s.llm_model or s.anthropic_model, s.llm_api_key, s.llm_timeout_seconds)
    raise ValueError(f"Unknown LLM_PROVIDER '{name}'")


def _has_anthropic_credentials() -> bool:
    import os

    s = get_settings()
    return bool(
        (s.llm_api_key and s.llm_api_key.startswith("sk-ant-"))
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


__all__ = ["ChatMessage", "LLMProvider", "get_llm_provider", "parse_json"]
