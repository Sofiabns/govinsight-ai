from decimal import ROUND_HALF_UP, Decimal
from statistics import median

import sqlalchemy as sa
from sqlalchemy import Engine

from govinsight.transform.tables import procurement

from .models import (
    DataQualityRunResult,
    QualityDimension,
    QualityRunStatus,
    RuleEvaluation,
    RuleSeverity,
)
from .repositories import (
    QualityResultRepository,
    QualityRunRepository,
    QualityWatermarkRepository,
)
from .rules import procurement_quality_rules
from .scoring import SCORE_QUANTUM, calculate_quality_score


class DataQualityExecutionError(RuntimeError):
    def __init__(self, run_id: int, code: str) -> None:
        self.run_id = run_id
        self.code = code
        super().__init__(f"Data quality execution failed with {code} for run {run_id}")


def _volume_evaluation(
    rows_evaluated: int,
    history: tuple[int, ...],
) -> RuleEvaluation:
    if len(history) < 3:
        return RuleEvaluation.from_counts(
            rule_code="ROW_VOLUME_ANOMALY",
            dimension=QualityDimension.VOLUME,
            severity=RuleSeverity.WARNING,
            checked_count=0,
            failed_count=0,
            details={"history_runs": len(history)},
        )
    baseline = Decimal(str(median(history)))
    if baseline == 0:
        deviation = Decimal("0.00") if rows_evaluated == 0 else Decimal("100.00")
    else:
        deviation = (abs(Decimal(rows_evaluated) - baseline) * 100 / baseline).quantize(
            SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
    return RuleEvaluation.from_counts(
        rule_code="ROW_VOLUME_ANOMALY",
        dimension=QualityDimension.VOLUME,
        severity=RuleSeverity.WARNING,
        checked_count=1,
        failed_count=int(deviation > Decimal("50.00")),
        details={
            "baseline_median": baseline,
            "deviation_percent": deviation,
            "history_runs": len(history),
        },
    )


class DataQualityService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._watermarks = QualityWatermarkRepository()
        self._runs = QualityRunRepository()
        self._results = QualityResultRepository()

    def run_pending(self) -> DataQualityRunResult:
        source_watermark = 0
        run_id: int | None = None
        try:
            with self._engine.begin() as connection:
                source_watermark = self._watermarks.silver_current(connection)
                if source_watermark == 0:
                    return DataQualityRunResult(
                        run_id=None,
                        source_watermark=0,
                        status=QualityRunStatus.NOOP,
                        rows_evaluated=0,
                        score=None,
                        blocking_failures=0,
                        reused=True,
                    )
                state = self._runs.start_or_get(connection, source_watermark)
                run_id = state.run_id
                if not state.created:
                    return self._runs.load(connection, run_id)

                rows_evaluated = connection.execute(
                    sa.select(sa.func.count()).select_from(procurement)
                ).scalar_one()
                evaluations = tuple(
                    RuleEvaluation.from_counts(
                        rule_code=rule.code,
                        dimension=rule.dimension,
                        severity=rule.severity,
                        checked_count=measurement.checked_count,
                        failed_count=measurement.failed_count,
                    )
                    for rule in procurement_quality_rules()
                    for measurement in [connection.execute(rule.statement).one()]
                )
                history = self._runs.successful_row_counts(connection)
                evaluations += (_volume_evaluation(rows_evaluated, history),)
                score = calculate_quality_score(evaluations)
                status = (
                    QualityRunStatus.PASSED
                    if score.blocking_failures == 0
                    else QualityRunStatus.FAILED
                )
                result = DataQualityRunResult(
                    run_id=run_id,
                    source_watermark=source_watermark,
                    status=status,
                    rows_evaluated=rows_evaluated,
                    score=score.overall,
                    blocking_failures=score.blocking_failures,
                    evaluations=evaluations,
                )
                self._results.replace(connection, run_id, evaluations)
                self._runs.complete(connection, run_id, result)
                if status is QualityRunStatus.PASSED:
                    self._watermarks.advance(connection, source_watermark)
                return result
        except sa.exc.SQLAlchemyError:
            if source_watermark == 0:
                raise DataQualityExecutionError(0, "QUALITY_QUERY_FAILED") from None
            with self._engine.begin() as connection:
                state = self._runs.start_or_get(connection, source_watermark)
                run_id = state.run_id
                self._runs.fail_execution(connection, run_id, "QUALITY_QUERY_FAILED")
            raise DataQualityExecutionError(run_id, "QUALITY_QUERY_FAILED") from None


__all__ = ["DataQualityExecutionError", "DataQualityService"]
