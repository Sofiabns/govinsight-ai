from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=4, gt=0)
    base_delay: float = Field(default=0.5, gt=0)
    max_delay: float = Field(default=8.0, gt=0)
    jitter_ratio: float = Field(default=0.1, ge=0, le=1)

    def delay_seconds(
        self,
        attempt: int,
        *,
        retry_after: str | None = None,
        random_value: float = 0.0,
        now: datetime | None = None,
    ) -> float:
        if attempt < 1:
            raise ValueError("attempt must be at least 1")
        if not 0 <= random_value <= 1:
            raise ValueError("random_value must be between 0 and 1")

        server_delay = self._parse_retry_after(retry_after, now=now)
        if server_delay is not None:
            return server_delay

        exponential = min(self.max_delay, self.base_delay * 2 ** (attempt - 1))
        return exponential * (1 + self.jitter_ratio * random_value)

    @staticmethod
    def _parse_retry_after(value: str | None, *, now: datetime | None) -> float | None:
        if value is None:
            return None

        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                current = now or datetime.now(UTC)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                seconds = (retry_at - current).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None

        return seconds if isfinite(seconds) and seconds >= 0 else None
