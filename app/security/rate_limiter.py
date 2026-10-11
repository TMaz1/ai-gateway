import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Thread-safe fixed-window limiter. State is per process, not distributed."""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        max_tracked_keys: int = 10_000,
    ) -> None:
        if limit < 1 or window_seconds < 1 or max_tracked_keys < 1:
            raise ValueError("rate-limit values must be positive")

        self.limit = limit
        self.window_seconds = window_seconds
        self.max_tracked_keys = max_tracked_keys
        self._windows: OrderedDict[str, tuple[int, int]] = OrderedDict()
        self._lock = Lock()

    def check(
        self,
        identity: str,
        now: float | None = None,
    ) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
        window_id = int(current // self.window_seconds)
        window_end = (window_id + 1) * self.window_seconds

        with self._lock:
            for key, (stored_window, _) in list(self._windows.items()):
                if stored_window < window_id:
                    self._windows.pop(key, None)

            existing = self._windows.get(identity)
            if existing is None or existing[0] != window_id:
                if (
                    identity not in self._windows
                    and len(self._windows) >= self.max_tracked_keys
                ):
                    # Fail closed when the bounded state table is full.
                    return RateLimitDecision(
                        False,
                        self.limit,
                        0,
                        max(1, int(window_end - current)),
                    )
                count = 0
            else:
                count = existing[1]
                self._windows.move_to_end(identity)

            if count >= self.limit:
                return RateLimitDecision(
                    False,
                    self.limit,
                    0,
                    max(1, int(window_end - current)),
                )

            count += 1
            self._windows[identity] = (window_id, count)

            return RateLimitDecision(
                True,
                self.limit,
                self.limit - count,
                0,
            )
