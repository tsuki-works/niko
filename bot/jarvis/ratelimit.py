"""Per-user in-memory rate limiter.

Sliding window: each user has a deque of timestamps; on `check_and_record`
we drop expired timestamps from the front and either reject (deque is at
capacity) or append.

In-memory only. A restart resets the limiter — fine for a small team
where the worst case is a teammate who hit the limit before deploy gets
20 fresh calls right after. PR-3b/4 may move this to Firestore if usage
patterns warrant.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Callable


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        max_per_window: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_per_window
        self._window = window_seconds
        self._clock = clock
        self._calls: dict[int, deque[float]] = {}

    def check_and_record(self, *, user_id: int) -> bool:
        """Return True if the call is allowed; False if rate-limited.

        On True, a timestamp is recorded against the user."""
        now = self._clock()
        cutoff = now - self._window
        timestamps = self._calls.setdefault(user_id, deque())
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= self._max:
            return False
        timestamps.append(now)
        return True
