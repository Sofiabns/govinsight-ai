from decimal import ROUND_FLOOR, Decimal

from govinsight.analytics.models import DistributionSummary, Measure

MINIMUM_OUTLIER_SAMPLE = 4


def _percentile(values: tuple[Decimal, ...], fraction: Decimal) -> Decimal:
    position = Decimal(len(values) - 1) * fraction
    lower = int(position.to_integral_value(rounding=ROUND_FLOOR))
    upper = min(lower + 1, len(values) - 1)
    weight = position - Decimal(lower)
    return values[lower] + (values[upper] - values[lower]) * weight


def describe(values: list[Decimal], measure: Measure) -> DistributionSummary:
    ordered = tuple(sorted(values))
    if not ordered:
        return DistributionSummary(
            measure=measure,
            sample_size=0,
            minimum=None,
            q1=None,
            median=None,
            q3=None,
            maximum=None,
            mean=None,
            iqr=None,
            lower_fence=None,
            upper_fence=None,
        )

    q1 = _percentile(ordered, Decimal("0.25"))
    median = _percentile(ordered, Decimal("0.5"))
    q3 = _percentile(ordered, Decimal("0.75"))
    iqr = q3 - q1
    enough_evidence = len(ordered) >= MINIMUM_OUTLIER_SAMPLE
    return DistributionSummary(
        measure=measure,
        sample_size=len(ordered),
        minimum=ordered[0],
        q1=q1,
        median=median,
        q3=q3,
        maximum=ordered[-1],
        mean=sum(ordered, start=Decimal(0)) / Decimal(len(ordered)),
        iqr=iqr,
        lower_fence=q1 - Decimal("1.5") * iqr if enough_evidence else None,
        upper_fence=q3 + Decimal("1.5") * iqr if enough_evidence else None,
    )


def detect_outlier_values(
    values: list[Decimal], distribution: DistributionSummary
) -> tuple[Decimal, ...]:
    if distribution.lower_fence is None or distribution.upper_fence is None:
        return ()
    return tuple(
        value
        for value in values
        if value < distribution.lower_fence or value > distribution.upper_fence
    )


__all__ = ["describe", "detect_outlier_values"]
