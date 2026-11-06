"""Small in-memory token-bucket rate limiter.

Adequate for a single API process. For multi-instance deployments, swap for a
shared store (Redis) behind the same `check()` call.
"""

from __future__ import annotations

import threading
import time

from app.core.config import get_settings
from app.core.errors import RateLimitedError


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, capacity: int, per_seconds: float, message: str | None = None) -> None:
        if not get_settings().rate_limit_enabled:
            return
        rate = capacity / per_seconds
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(capacity), now))
            tokens = min(capacity, tokens + (now - last) * rate)
            if tokens < 1:
                wait = int((1 - tokens) / rate) + 1
                raise RateLimitedError(message or f"Too many requests. Try again in {wait} seconds.", details={"retry_after": wait})
            self._buckets[key] = (tokens - 1, now)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()
