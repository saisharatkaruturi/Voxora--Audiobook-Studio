from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatMessage:
    role: str  # user | assistant
    content: str


class LLMProvider(ABC):
    name: str = "base"
    is_local: bool = True
    privacy_note: str = ""

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def is_available(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    def complete(self, system: str, messages: list[ChatMessage], *, max_tokens: int = 2000, json_schema: dict | None = None) -> str:
        """Return the model's text. With `json_schema`, the text is a JSON document
        matching the schema (providers use native structured output where available)."""

    def complete_json(self, system: str, messages: list[ChatMessage], schema: dict, *, max_tokens: int = 4000) -> dict:
        text = self.complete(system, messages, max_tokens=max_tokens, json_schema=schema)
        return parse_json(text)

    def describe(self) -> dict:
        ok, reason = self.is_available()
        return {"name": self.name, "model": self.model, "available": ok, "reason": reason, "is_local": self.is_local, "privacy_note": self.privacy_note}


def parse_json(text: str) -> dict:
    """Parse JSON from model output, tolerating code fences or leading prose."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start >= 0:
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start : end + 1])
        raise
