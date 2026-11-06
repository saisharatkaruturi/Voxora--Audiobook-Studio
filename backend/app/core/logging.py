"""Structured logging.

`log.info("chapter.completed", book_id=..., duration=...)` produces either a
human-readable line or a JSON object, depending on LOG_JSON. Never pass API
keys, passwords, or document text as fields.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

_REDACT_KEYS = {"password", "api_key", "token", "authorization", "secret", "text", "content"}


class _Formatter(logging.Formatter):
    def __init__(self, as_json: bool):
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = getattr(record, "fields", {}) or {}
        safe = {k: ("[redacted]" if k.lower() in _REDACT_KEYS else v) for k, v in fields.items()}
        if self.as_json:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
                "level": record.levelname.lower(),
                "logger": record.name,
                "event": record.getMessage(),
                **safe,
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str)
        extras = " ".join(f"{k}={v}" for k, v in safe.items())
        line = f"{time.strftime('%H:%M:%S', time.localtime(record.created))} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if extras:
            line += f"  {extras}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class StructuredLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, event: str, exc_info: bool = False, **fields: Any) -> None:
        self._logger.log(level, event, extra={"fields": fields}, exc_info=exc_info)

    def debug(self, event: str, **fields: Any) -> None:
        self._log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> None:
        self._log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log(logging.WARNING, event, **fields)

    def error(self, event: str, exc_info: bool = False, **fields: Any) -> None:
        self._log(logging.ERROR, event, exc_info=exc_info, **fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._log(logging.ERROR, event, exc_info=True, **fields)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)


def configure_logging(level: str = "INFO", as_json: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter(as_json))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "multipart", "PIL", "urllib3", "asyncio", "fontTools"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
