from decimal import Decimal

from govinsight.quality.models import (
    QualityDimension,
    RuleEvaluation,
    RuleSeverity,
    RuleStatus,
)
from govinsight.quality.scoring import calculate_quality_score


def _evaluation(
    code: str,
    dimension: QualityDimension,
    checked: int,
    failed: int,
    *,
    severity: RuleSeverity = RuleSeverity.BLOCKING,
) -> RuleEvaluation:
    return RuleEvaluation.from_counts(
        rule_code=code,
        dimension=dimension,
        severity=severity,
        checked_count=checked,
        failed_count=failed,
    )


def test_weighted_quality_score_is_exact_and_ignores_volume_warning() -> None:
    evaluations = (
        _evaluation(
            "REQUIRED_TEXT_PRESENT",
            QualityDimension.COMPLETENESS,
            10,
            2,
        ),
        _evaluation("CNPJ_FORMAT_VALID", QualityDimension.VALIDITY, 10, 0),
        _evaluation("NATURAL_KEY_UNIQUE", QualityDimension.UNIQUENESS, 10, 0),
        _evaluation("PROPOSAL_WINDOW_VALID", QualityDimension.CONSISTENCY, 10, 0),
        _evaluation("BRONZE_LINEAGE_VALID", QualityDimension.INTEGRITY, 10, 0),
        _evaluation(
            "ROW_VOLUME_ANOMALY",
            QualityDimension.VOLUME,
            1,
            1,
            severity=RuleSeverity.WARNING,
        ),
    )

    result = calculate_quality_score(evaluations)

    assert result.overall == Decimal("94.00")
    assert result.dimensions == {
        QualityDimension.COMPLETENESS: Decimal("80.00"),
        QualityDimension.VALIDITY: Decimal("100.00"),
        QualityDimension.UNIQUENESS: Decimal("100.00"),
        QualityDimension.CONSISTENCY: Decimal("100.00"),
        QualityDimension.INTEGRITY: Decimal("100.00"),
    }
    assert result.blocking_failures == 1
    assert evaluations[-1].status is RuleStatus.WARNING


def test_empty_dataset_is_zero_and_non_applicable_rules_are_not_evaluated() -> None:
    evaluations = (
        _evaluation("DATASET_NOT_EMPTY", QualityDimension.COMPLETENESS, 1, 1),
        _evaluation("UF_DOMAIN_VALID", QualityDimension.VALIDITY, 0, 0),
    )

    result = calculate_quality_score(evaluations)

    assert result.overall == Decimal("0.00")
    assert result.dimensions == {QualityDimension.COMPLETENESS: Decimal("0.00")}
    assert result.blocking_failures == 1
    assert evaluations[1].status is RuleStatus.NOT_EVALUATED
    assert evaluations[1].score is None
