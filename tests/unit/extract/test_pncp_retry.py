from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
from pydantic import ValidationError

from govinsight.extract.pncp.errors import PNCPHTTPError
from govinsight.extract.pncp.retry import RetryPolicy


@pytest.mark.parametrize(
    ("attempt", "max_delay", "expected"),
    [
        (1, 8.0, 0.5),
        (3, 8.0, 2.0),
        (3, 1.0, 1.0),
    ],
)
def test_exponential_delay_uses_attempt_and_cap(
    attempt: int, max_delay: float, expected: float
) -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=max_delay, jitter_ratio=0.0)

    assert policy.delay_seconds(attempt, random_value=0.0) == expected


def test_jitter_is_applied_after_exponential_cap() -> None:
    policy = RetryPolicy(base_delay=1.0, max_delay=2.0, jitter_ratio=0.25)

    assert policy.delay_seconds(3, random_value=0.4) == pytest.approx(2.2)


def test_numeric_retry_after_is_honored_without_client_cap() -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=1.0, jitter_ratio=0.0)

    assert policy.delay_seconds(1, retry_after="7", random_value=0.0) == 7.0


def test_http_date_retry_after_uses_utc_delta() -> None:
    now = datetime(2025, 8, 1, 12, 0, tzinfo=UTC)
    retry_at = format_datetime(now + timedelta(seconds=9), usegmt=True)
    policy = RetryPolicy(jitter_ratio=0.0)

    assert policy.delay_seconds(1, retry_after=retry_at, random_value=0.0, now=now) == 9.0


@pytest.mark.parametrize(
    "retry_after",
    ["invalid", "-4", "Infinity", "Thu, 31 Jul 2025 12:00:00 GMT"],
)
def test_invalid_or_elapsed_retry_after_falls_back(retry_after: str) -> None:
    policy = RetryPolicy(base_delay=0.5, max_delay=8.0, jitter_ratio=0.0)
    now = datetime(2025, 8, 1, 12, 0, tzinfo=UTC)

    assert policy.delay_seconds(2, retry_after=retry_after, random_value=0.0, now=now) == 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay": 0},
        {"max_delay": 0},
        {"jitter_ratio": -0.1},
        {"jitter_ratio": 1.1},
    ],
)
def test_policy_rejects_unsafe_values(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(**kwargs)


def test_http_error_message_never_contains_response_body() -> None:
    error = PNCPHTTPError(
        status_code=503,
        endpoint="/v1/contratacoes/publicacao",
        attempt=4,
    )

    assert str(error) == (
        "PNCP request failed with HTTP 503 at /v1/contratacoes/publicacao on attempt 4"
    )
    assert not hasattr(error, "response_body")
