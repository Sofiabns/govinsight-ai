from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class WarehouseLoadStatus(StrEnum):
    NOOP = "NOOP"
    LOADED = "LOADED"


class WarehouseLoadResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: WarehouseLoadStatus
    source_watermark: Annotated[int, Field(ge=0)]
    rows_loaded: Annotated[int, Field(ge=0)]
    reused: bool = False


class WarehouseWatermarkState(BaseModel):
    model_config = ConfigDict(frozen=True)

    silver: Annotated[int, Field(ge=0)]
    quality: Annotated[int, Field(ge=0)]
    gold: Annotated[int, Field(ge=0)]


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    silver_rows: Annotated[int, Field(ge=0)]
    fact_rows: Annotated[int, Field(ge=0)]
    missing_in_fact: Annotated[int, Field(ge=0)]
    missing_in_silver: Annotated[int, Field(ge=0)]
    orphan_foreign_keys: Annotated[int, Field(ge=0)]
    lineage_mismatches: Annotated[int, Field(ge=0)]
    estimated_silver: Decimal
    estimated_fact: Decimal
    estimated_nulls_silver: Annotated[int, Field(ge=0)]
    estimated_nulls_fact: Annotated[int, Field(ge=0)]
    homologated_silver: Decimal
    homologated_fact: Decimal
    homologated_nulls_silver: Annotated[int, Field(ge=0)]
    homologated_nulls_fact: Annotated[int, Field(ge=0)]

    @property
    def is_valid(self) -> bool:
        return (
            self.silver_rows == self.fact_rows
            and self.missing_in_fact == self.missing_in_silver == 0
            and self.orphan_foreign_keys == self.lineage_mismatches == 0
            and self.estimated_silver == self.estimated_fact
            and self.estimated_nulls_silver == self.estimated_nulls_fact
            and self.homologated_silver == self.homologated_fact
            and self.homologated_nulls_silver == self.homologated_nulls_fact
        )


class WarehouseStateError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


__all__ = [
    "ReconciliationResult",
    "WarehouseLoadResult",
    "WarehouseLoadStatus",
    "WarehouseStateError",
    "WarehouseWatermarkState",
]
