"""Adaptive concurrency for cloud speech services (AIMD, like TCP congestion control).

Every request to the service takes a slot. While requests succeed the limit
creeps up (additive increase); a timeout or throttle cuts it (multiplicative
decrease). Many chapters can synthesize at once and together they converge on
the fastest rate the service tolerates right now, instead of a fixed guess that
is either too timid or trips timeouts.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class AdaptiveLimiter:
    def __init__(self, start: int, minimum: int, maximum: int, increase_every: int = 4):
        self.limit = float(start)
        self.minimum = minimum
        self.maximum = maximum
        self.increase_every = increase_every
        self.in_flight = 0
        self._ok_streak = 0
        self._last_cut = 0.0
        self._cond = threading.Condition()

    @contextmanager
    def slot(self):
        with self._cond:
            while self.in_flight >= int(self.limit):
                self._cond.wait(timeout=1.0)
            self.in_flight += 1
        ok = False
        try:
            yield
            ok = True
        finally:
            with self._cond:
                self.in_flight -= 1
                if ok:
                    self._ok_streak += 1
                    if self._ok_streak >= self.increase_every and self.limit < self.maximum:
                        self.limit = min(self.maximum, self.limit + 1)
                        self._ok_streak = 0
                self._cond.notify_all()

    def congestion(self) -> None:
        """A request timed out or was throttled: back off (at most once per 2s, since
        one overload usually fails several in-flight requests together)."""
        with self._cond:
            now = time.monotonic()
            if now - self._last_cut > 2.0:
                self.limit = max(self.minimum, self.limit * 0.7)
                self._last_cut = now
            self._ok_streak = 0

    def snapshot(self) -> dict:
        return {"limit": int(self.limit), "in_flight": self.in_flight}
