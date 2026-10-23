"""In-memory sliding-window rate limiter."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0


class SlidingWindowLimiter:
    """Simple per-key limiter suitable for a single-process prototype.

    For a multi-process deployment replace it with a shared store (Redis) or
    enforce limits at the reverse proxy.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(
        self, key: str, *, limit: int, window_seconds: float
    ) -> RateLimitResult:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])) + 1)
                return RateLimitResult(False, retry_after)
            events.append(now)
            # Opportunistically drop empty/dead keys.
            if len(self._events) > 2048:
                for item_key in list(self._events):
                    bucket = self._events[item_key]
                    while bucket and bucket[0] <= cutoff:
                        bucket.popleft()
                    if not bucket:
                        self._events.pop(item_key, None)
            return RateLimitResult(True, 0)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
