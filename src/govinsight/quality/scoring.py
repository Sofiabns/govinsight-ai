from decimal import ROUND_HALF_UP, Decimal

from .models import (
    SCORE_QUANTUM,
    QualityDimension,
    QualityScore,
    RuleEvaluation,
    RuleSeverity,
    RuleStatus,
)

DIMENSION_WEIGHTS = {
    QualityDimension.COMPLETENESS: Decimal("0.30"),
    QualityDimension.VALIDITY: Decimal("0.25"),
    QualityDimension.UNIQUENESS: Decimal("0.20"),
    QualityDimension.CONSISTENCY: Decimal("0.15"),
    QualityDimension.INTEGRITY: Decimal("0.10"),
}


def calculate_quality_score(evaluations: tuple[RuleEvaluation, ...]) -> QualityScore:
    dimensions: dict[QualityDimension, Decimal] = {}
    for dimension in DIMENSION_WEIGHTS:
        scores = [
            item.score
            for item in evaluations
            if item.dimension is dimension and item.score is not None
        ]
        if scores:
            dimensions[dimension] = (sum(scores, Decimal()) / len(scores)).quantize(
                SCORE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )

    blocking_failures = sum(
        item.severity is RuleSeverity.BLOCKING and item.status is RuleStatus.FAILED
        for item in evaluations
    )
    empty_dataset = any(
        item.rule_code == "DATASET_NOT_EMPTY" and item.status is RuleStatus.FAILED
        for item in evaluations
    )
    included_weight = sum(
        (DIMENSION_WEIGHTS[dimension] for dimension in dimensions),
        Decimal(),
    )
    if empty_dataset or included_weight == 0:
        overall = Decimal("0.00")
    else:
        weighted = sum(
            (dimensions[dimension] * DIMENSION_WEIGHTS[dimension] for dimension in dimensions),
            Decimal(),
        )
        overall = (weighted / included_weight).quantize(
            SCORE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    return QualityScore(
        overall=overall,
        dimensions=dimensions,
        blocking_failures=blocking_failures,
    )
