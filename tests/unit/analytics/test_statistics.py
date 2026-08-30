from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from govinsight.analytics.models import AnalyticsFilters, Measure
from govinsight.analytics.statistics import describe, detect_outlier_values


def test_filters_reject_reversed_period() -> None:
    """Catch queries whose end date precedes their start date."""
    with pytest.raises(ValidationError):
        AnalyticsFilters(start_date=date(2025, 2, 1), end_date=date(2025, 1, 31))


def test_describe_uses_decimal_quartiles_without_float_rounding() -> None:
    """Catch quartile formulas that drift through binary floating-point conversion."""
    values = [Decimal(value) for value in ("10", "11", "12", "13", "100")]

    result = describe(values, Measure.HOMOLOGATED)

    assert result.sample_size == 5
    assert result.minimum == Decimal("10")
    assert result.q1 == Decimal("11")
    assert result.median == Decimal("12")
    assert result.q3 == Decimal("13")
    assert result.maximum == Decimal("100")
    assert result.mean == Decimal("29.2")
    assert result.iqr == Decimal("2")
    assert result.lower_fence == Decimal("8.0")
    assert result.upper_fence == Decimal("16.0")
    assert detect_outlier_values(values, result) == (Decimal("100"),)


def test_small_sample_is_described_but_not_classified_as_outlier() -> None:
    """Catch unstable outlier labels produced from insufficient evidence."""
    values = [Decimal("10"), Decimal("100"), Decimal("1000")]

    result = describe(values, Measure.ESTIMATED)

    assert result.sample_size == 3
    assert result.lower_fence is None
    assert result.upper_fence is None
    assert detect_outlier_values(values, result) == ()


def test_empty_sample_has_explicit_null_distribution() -> None:
    """Catch fabricated zero-valued statistics for a sample with no values."""
    result = describe([], Measure.HOMOLOGATED)

    assert result.sample_size == 0
    assert result.minimum is None
    assert result.mean is None
    assert result.iqr is None
    assert detect_outlier_values([], result) == ()
