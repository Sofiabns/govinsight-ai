from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RawDataset(StrEnum):
    PROCUREMENTS = "procurements"
    CONTRACTS = "contracts"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RawCapture(BaseModel):
    model_config = ConfigDict(frozen=True)

    etl_run_id: UUID
    source: str
    dataset: RawDataset
    endpoint: str
    request_params: dict[str, str | int]
    request_fingerprint: Hash
    window_start: date
    window_end: date
    page_number: Annotated[int, Field(ge=1)]
    http_status: Annotated[int, Field(ge=200, le=299)]
    raw_body: str
    body_sha256: Hash
    record_count: Annotated[int, Field(ge=0)]
    collected_at: datetime
    duration_ms: Annotated[float, Field(ge=0)]

    @model_validator(mode="after")
    def validate_window(self) -> "RawCapture":
        if self.window_end < self.window_start:
            raise ValueError("window_end must not precede window_start")
        if self.collected_at.tzinfo is None or self.collected_at.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        if self.collected_at.utcoffset().total_seconds() != 0:
            raise ValueError("collected_at must be UTC")
        return self


class InsertOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    inserted: bool
    raw_response_id: int | None


class IngestionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    status: RunStatus
    pages_processed: Annotated[int, Field(ge=0)]
    records_received: Annotated[int, Field(ge=0)]
    records_inserted: Annotated[int, Field(ge=0)]
    records_duplicate: Annotated[int, Field(ge=0)]
