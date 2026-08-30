from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Measure(StrEnum):
    ESTIMATED = "estimated"
    HOMOLOGATED = "homologated"


class RankDimension(StrEnum):
    ORGANIZATION = "organization"
    STATE = "state"
    MODALITY = "modality"


class AnalyticsFilters(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date | None = None
    end_date: date | None = None
    organization_key: Annotated[int | None, Field(gt=0)] = None
    uf: str | None = None
    modality_key: Annotated[int | None, Field(gt=0)] = None

    @field_validator("uf")
    @classmethod
    def normalize_uf(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized != "UNKNOWN" and (len(normalized) != 2 or not normalized.isalpha()):
            raise ValueError("uf must contain two letters or UNKNOWN")
        return normalized

    @model_validator(mode="after")
    def validate_period(self) -> "AnalyticsFilters":
        if self.start_date is not None and self.end_date is not None:
            if self.end_date < self.start_date:
                raise ValueError("end_date must be on or after start_date")
        return self


class AnalyticsSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    procurement_count: Annotated[int, Field(ge=0)]
    estimated_value_count: Annotated[int, Field(ge=0)]
    estimated_total: Decimal | None
    estimated_average: Decimal | None
    homologated_value_count: Annotated[int, Field(ge=0)]
    homologated_total: Decimal | None
    homologated_average: Decimal | None


class RankingRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: Annotated[int, Field(gt=0)]
    dimension: RankDimension
    key: str
    label: str
    procurement_count: Annotated[int, Field(ge=0)]
    total: Decimal | None
    average: Decimal | None
    share: Decimal | None


class MonthlyTrend(BaseModel):
    model_config = ConfigDict(frozen=True)

    month: date
    procurement_count: Annotated[int, Field(ge=0)]
    estimated_total: Decimal | None
    estimated_average: Decimal | None
    homologated_total: Decimal | None
    homologated_average: Decimal | None
    estimated_growth_rate: Decimal | None
    homologated_growth_rate: Decimal | None


class DistributionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    measure: Measure
    sample_size: Annotated[int, Field(ge=0)]
    minimum: Decimal | None
    q1: Decimal | None
    median: Decimal | None
    q3: Decimal | None
    maximum: Decimal | None
    mean: Decimal | None
    iqr: Decimal | None
    lower_fence: Decimal | None
    upper_fence: Decimal | None


class OutlierRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    numero_controle_pncp: str
    value: Decimal


class OutlierResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    distribution: DistributionSummary
    outliers: tuple[OutlierRow, ...]


__all__ = [
    "AnalyticsFilters",
    "AnalyticsSummary",
    "DistributionSummary",
    "Measure",
    "MonthlyTrend",
    "OutlierResult",
    "OutlierRow",
    "RankDimension",
    "RankingRow",
]
