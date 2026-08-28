"""Bounded in-process failure limiter for the single-process v1 server."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Callable

from .models import FailureLimitDecision


class AuthenticationFailureLimiter:
    """Limit failures independently by socket origin and token selector."""

    def __init__(
        self,
        *,
        origin_limit: int = 20,
        selector_limit: int = 10,
        window_seconds: int = 600,
        max_buckets: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(origin_limit, selector_limit, window_seconds, max_buckets) <= 0:
            raise ValueError("failure limits and window must be positive")
        self._origin_limit = origin_limit
        self._selector_limit = selector_limit
        self._window = window_seconds
        self._max_buckets = max_buckets
        self._clock = clock
        self._origin: dict[str, deque[float]] = defaultdict(deque)
        self._selector: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def record_failure(self, *, origin: str, selector: str) -> FailureLimitDecision:
        now = self._clock()
        async with self._lock:
            origin_events = self._events(self._origin, origin or "unknown", now)
            origin_events.append(now)
            if len(origin_events) > self._origin_limit:
                return self._limited(now, origin_events[0])
            selector_events = self._events(self._selector, selector or "malformed", now)
            selector_events.append(now)
            if len(selector_events) <= self._selector_limit:
                return FailureLimitDecision(True)
            return self._limited(now, selector_events[0])

    def _limited(self, now: float, oldest: float) -> FailureLimitDecision:
        return FailureLimitDecision(
            False,
            max(1, round(self._window - (now - oldest))),
        )

    def _make_room(self, buckets: dict[str, deque[float]], now: float) -> None:
        if len(buckets) < self._max_buckets:
            return
        cutoff = now - self._window
        for key in tuple(buckets):
            events = buckets[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del buckets[key]
        while len(buckets) >= self._max_buckets:
            del buckets[next(iter(buckets))]

    def _events(
        self,
        buckets: dict[str, deque[float]],
        key: str,
        now: float,
    ) -> deque[float]:
        if key not in buckets:
            self._make_room(buckets, now)
        events = buckets[key]
        cutoff = now - self._window
        while events and events[0] <= cutoff:
            events.popleft()
        return events


__all__ = ["AuthenticationFailureLimiter"]
