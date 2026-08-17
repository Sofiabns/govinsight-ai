import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from govinsight.config import get_settings

RAW_CHECKS = {
    "ck_raw_response_body_sha256",
    "ck_raw_response_dataset",
    "ck_raw_response_duration_ms_non_negative",
    "ck_raw_response_http_status",
    "ck_raw_response_page_number_positive",
    "ck_raw_response_record_count_non_negative",
    "ck_raw_response_request_fingerprint",
    "ck_raw_response_window",
}
ETL_RUN_CHECKS = {
    "ck_etl_run_dataset",
    "ck_etl_run_mode",
    "ck_etl_run_pages_processed_non_negative",
    "ck_etl_run_records_duplicate_non_negative",
    "ck_etl_run_records_inserted_non_negative",
    "ck_etl_run_records_received_non_negative",
    "ck_etl_run_status",
    "ck_etl_run_terminal_time",
}
CHECKPOINT_CHECKS = {
    "ck_extraction_checkpoint_dataset",
    "ck_extraction_checkpoint_last_successful_page_positive",
    "ck_extraction_checkpoint_mode",
    "ck_extraction_checkpoint_scope_fingerprint",
}
RAW_UNIQUE_COLUMNS = [
    "source",
    "dataset",
    "endpoint",
    "request_fingerprint",
    "body_sha256",
]


@pytest.mark.integration
def test_raw_migration_creates_constraints_and_downgrades_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for the migration integration test")

    parsed_url = make_url(database_url)
    monkeypatch.setenv("GOVINSIGHT_POSTGRES_DB", parsed_url.database or "")
    monkeypatch.setenv("GOVINSIGHT_POSTGRES_USER", parsed_url.username or "")
    monkeypatch.setenv("GOVINSIGHT_POSTGRES_PASSWORD", parsed_url.password or "")
    monkeypatch.setenv("GOVINSIGHT_POSTGRES_HOST", parsed_url.host or "")
    monkeypatch.setenv("GOVINSIGHT_POSTGRES_PORT", str(parsed_url.port or 5432))
    get_settings.cache_clear()

    alembic_config = Config("alembic.ini")
    engine = create_engine(database_url, pool_pre_ping=True)
    command.upgrade(alembic_config, "head")

    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="bronze")) >= {"raw_api_response"}
        assert set(inspector.get_table_names(schema="control")) >= {
            "etl_run",
            "extraction_checkpoint",
            "etl_watermark",
        }

        raw_unique_constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints("raw_api_response", schema="bronze")
        }
        assert raw_unique_constraints["uq_raw_response_identity_body"]["column_names"] == (
            RAW_UNIQUE_COLUMNS
        )

        raw_foreign_keys = {
            constraint["name"]: constraint
            for constraint in inspector.get_foreign_keys("raw_api_response", schema="bronze")
        }
        raw_run_fk = raw_foreign_keys["fk_raw_response_etl_run"]
        assert raw_run_fk["constrained_columns"] == ["etl_run_id"]
        assert raw_run_fk["referred_schema"] == "control"
        assert raw_run_fk["referred_table"] == "etl_run"
        assert raw_run_fk["referred_columns"] == ["id"]

        raw_check_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("raw_api_response", schema="bronze")
        }
        assert raw_check_names >= RAW_CHECKS

        run_check_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("etl_run", schema="control")
        }
        assert run_check_names >= ETL_RUN_CHECKS

        checkpoint_check_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "extraction_checkpoint", schema="control"
            )
        }
        assert checkpoint_check_names >= CHECKPOINT_CHECKS

        watermark_check_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("etl_watermark", schema="control")
        }
        assert watermark_check_names >= {"ck_etl_watermark_dataset"}

        raw_index_names = {
            index["name"] for index in inspector.get_indexes("raw_api_response", schema="bronze")
        }
        assert "ix_raw_response_dataset_collected_at" in raw_index_names

        command.downgrade(alembic_config, "20260817_0001")
        downgraded_inspector = inspect(engine)
        assert "raw_api_response" not in downgraded_inspector.get_table_names(schema="bronze")
        assert set(downgraded_inspector.get_table_names(schema="control")).isdisjoint(
            {"etl_run", "extraction_checkpoint", "etl_watermark"}
        )
        assert set(downgraded_inspector.get_schema_names()) >= {
            "bronze",
            "silver",
            "gold",
            "control",
        }
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
        get_settings.cache_clear()
