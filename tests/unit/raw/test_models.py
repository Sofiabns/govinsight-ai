from datetime import UTC, date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from govinsight.raw.models import IngestionResult, InsertOutcome, RawCapture, RunStatus

RUN_ID = uuid4()
VALID_CAPTURE = {
    "etl_run_id": RUN_ID,
    "source": "pncp",
    "dataset": "procurements",
    "endpoint": "/v1/contratacoes/publicacao",
    "request_params": {"pagina": 1, "tamanhoPagina": 50},
    "request_fingerprint": "a" * 64,
    "window_start": date(2025, 8, 1),
    "window_end": date(2025, 8, 31),
    "page_number": 1,
    "http_status": 200,
    "raw_body": '{"data":[]}',
    "body_sha256": "b" * 64,
    "record_count": 0,
    "collected_at": datetime(2025, 8, 1, 12, tzinfo=UTC),
    "duration_ms": 1.25,
}


def test_raw_capture_accepts_valid_successful_response() -> None:
    assert RawCapture(**VALID_CAPTURE).etl_run_id == RUN_ID


@pytest.mark.parametrize(
    ("field", "value"),
    [("page_number", 0), ("http_status", 199), ("duration_ms", -0.001), ("record_count", -1)],
)
def test_raw_capture_rejects_invalid_metadata(field: str, value: int | float) -> None:
    with pytest.raises(ValidationError):
        RawCapture(**{**VALID_CAPTURE, field: value})


def test_raw_capture_rejects_reversed_window_bad_hashes_and_naive_datetime() -> None:
    for field, value in (
        ("window_end", date(2025, 7, 31)),
        ("body_sha256", "A" * 64),
        ("request_fingerprint", "short"),
        ("collected_at", datetime(2025, 8, 1, 12)),
    ):
        with pytest.raises(ValidationError):
            RawCapture(**{**VALID_CAPTURE, field: value})


def test_raw_capture_rejects_non_utc_collection_time() -> None:
    with pytest.raises(ValidationError):
        RawCapture(
            **{
                **VALID_CAPTURE,
                "collected_at": datetime(2025, 8, 1, 12, tzinfo=timezone(timedelta(hours=2))),
            }
        )


def test_insert_outcome_and_ingestion_result_are_frozen() -> None:
    assert InsertOutcome(inserted=False, raw_response_id=None).inserted is False
    result = IngestionResult(
        run_id=UUID(int=0),
        status=RunStatus.SUCCEEDED,
        pages_processed=2,
        records_received=3,
        records_inserted=2,
        records_duplicate=1,
    )
    assert result.records_duplicate == 1
    with pytest.raises(ValidationError):
        result.pages_processed = 4
