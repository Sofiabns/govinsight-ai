from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class FixedWindowRateLimiter:
    """Small process-local guard; production edge limits remain the outer boundary."""

    def __init__(self, *, limit: int = 20, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> RateLimitDecision:
        now = monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                retry_after = max(1, round(self.window_seconds - (now - timestamps[0])))
                return RateLimitDecision(False, retry_after)
            timestamps.append(now)
            return RateLimitDecision(True)


__all__ = ["FixedWindowRateLimiter", "RateLimitDecision"]
