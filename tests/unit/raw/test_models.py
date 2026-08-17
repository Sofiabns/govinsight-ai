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
    "request_fingerprint": "40ecef2b994d742414d973604421ec4e2692ae03cb1352518d4510dd8707e746",
    "window_start": date(2025, 8, 1),
    "window_end": date(2025, 8, 31),
    "page_number": 1,
    "http_status": 200,
    "raw_body": "body",
    "body_sha256": "230d8358dc8e8890b4c58deeb62912ee2f20357ae92a5cc861b98e68fe31acb5",
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


@pytest.mark.parametrize(
    "field",
    ["request_fingerprint", "body_sha256"],
)
def test_raw_capture_rejects_hashes_inconsistent_with_payload(field: str) -> None:
    replacement = {
        "request_fingerprint": "a" * 64,
        "body_sha256": "b" * 64,
    }[field]
    with pytest.raises(ValidationError):
        RawCapture(**{**VALID_CAPTURE, field: replacement})


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
