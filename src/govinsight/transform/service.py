import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from .procurement import parse_procurement
from .repositories import (
    BronzeProcurementRepository,
    ProcurementRepository,
    RejectedRecordRepository,
    SilverWatermarkRepository,
    WriteOutcome,
)


class SilverEnvelopeError(RuntimeError):
    def __init__(self, raw_response_id: int, code: str) -> None:
        self.raw_response_id = raw_response_id
        self.code = code
        super().__init__(f"Silver envelope error {code} for RAW response {raw_response_id}")


class TransformationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    responses_processed: Annotated[int, Field(ge=0)]
    records_received: Annotated[int, Field(ge=0)]
    inserted: Annotated[int, Field(ge=0)]
    updated: Annotated[int, Field(ge=0)]
    unchanged: Annotated[int, Field(ge=0)]
    rejected: Annotated[int, Field(ge=0)]
    last_raw_response_id: Annotated[int, Field(ge=0)]


class SilverTransformationService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._bronze = BronzeProcurementRepository()
        self._procurements = ProcurementRepository()
        self._rejections = RejectedRecordRepository()
        self._watermark = SilverWatermarkRepository()

    def transform_pending(self, limit: int = 100) -> TransformationResult:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._engine.connect() as connection:
            starting_watermark = self._watermark.current(connection)
            pending = self._bronze.pending(connection, starting_watermark, limit)

        responses_processed = 0
        records_received = 0
        inserted = 0
        updated = 0
        unchanged = 0
        rejected = 0
        last_raw_response_id = starting_watermark

        for raw in pending:
            raw_id = int(raw["id"])
            parsed: object | None = None
            parse_failed = False
            try:
                parsed = json.loads(raw["raw_body"])
            except (json.JSONDecodeError, TypeError):
                parse_failed = True
            if parse_failed:
                raise SilverEnvelopeError(raw_id, "INVALID_JSON")
            if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
                raise SilverEnvelopeError(raw_id, "INVALID_ENVELOPE")
            records = parsed["data"]

            with self._engine.begin() as connection:
                current_watermark = self._watermark.current(connection, lock=True)
                if raw_id <= current_watermark:
                    last_raw_response_id = max(last_raw_response_id, current_watermark)
                    continue
                for index, record in enumerate(records):
                    outcome = parse_procurement(
                        record,
                        raw_response_id=raw_id,
                        record_index=index,
                    )
                    if outcome.procurement is not None:
                        write = self._procurements.upsert(connection, outcome.procurement)
                        if write is WriteOutcome.INSERTED:
                            inserted += 1
                        elif write is WriteOutcome.UPDATED:
                            updated += 1
                        else:
                            unchanged += 1
                    elif outcome.rejection is not None and self._rejections.insert(
                        connection, outcome.rejection
                    ):
                        rejected += 1
                self._watermark.advance(connection, raw_id)

            responses_processed += 1
            records_received += len(records)
            last_raw_response_id = raw_id

        return TransformationResult(
            responses_processed=responses_processed,
            records_received=records_received,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            rejected=rejected,
            last_raw_response_id=last_raw_response_id,
        )
