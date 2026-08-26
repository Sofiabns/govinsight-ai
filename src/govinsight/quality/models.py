from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCORE_QUANTUM = Decimal("0.01")


class QualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    CONSISTENCY = "consistency"
    INTEGRITY = "integrity"
    VOLUME = "volume"


class RuleSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class RuleStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    NOT_EVALUATED = "not_evaluated"


class QualityRunStatus(StrEnum):
    NOOP = "NOOP"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RuleEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_code: str
    dimension: QualityDimension
    severity: RuleSeverity
    status: RuleStatus
    checked_count: Annotated[int, Field(ge=0)]
    failed_count: Annotated[int, Field(ge=0)]
    score: Annotated[Decimal, Field(ge=0, le=100)] | None
    details: dict[str, int | str | Decimal] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_counts(self) -> "RuleEvaluation":
        if self.failed_count > self.checked_count:
            raise ValueError("failed_count cannot exceed checked_count")
        return self

    @classmethod
    def from_counts(
        cls,
        *,
        rule_code: str,
        dimension: QualityDimension,
        severity: RuleSeverity,
        checked_count: int,
        failed_count: int,
        details: dict[str, int | str | Decimal] | None = None,
    ) -> "RuleEvaluation":
        if checked_count == 0:
            status = RuleStatus.NOT_EVALUATED
            score = None
        else:
            score = (Decimal(checked_count - failed_count) * 100 / Decimal(checked_count)).quantize(
                SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            if failed_count == 0:
                status = RuleStatus.PASSED
            elif severity is RuleSeverity.WARNING:
                status = RuleStatus.WARNING
            else:
                status = RuleStatus.FAILED
        return cls(
            rule_code=rule_code,
            dimension=dimension,
            severity=severity,
            status=status,
            checked_count=checked_count,
            failed_count=failed_count,
            score=score,
            details=details or {},
        )


class QualityScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall: Annotated[Decimal, Field(ge=0, le=100)]
    dimensions: dict[QualityDimension, Annotated[Decimal, Field(ge=0, le=100)]]
    blocking_failures: Annotated[int, Field(ge=0)]


class DataQualityRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: Annotated[int, Field(gt=0)] | None
    source_watermark: Annotated[int, Field(ge=0)]
    status: QualityRunStatus
    rows_evaluated: Annotated[int, Field(ge=0)]
    score: Annotated[Decimal, Field(ge=0, le=100)] | None
    blocking_failures: Annotated[int, Field(ge=0)]
    evaluations: tuple[RuleEvaluation, ...] = ()
    reused: bool = False
