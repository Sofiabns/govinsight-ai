import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from govinsight.config import get_settings

PROCUREMENT_CHECKS = {
    "ck_silver_procurement_cnpj",
    "ck_silver_procurement_hash",
    "ck_silver_procurement_ibge",
    "ck_silver_procurement_proposal_window",
    "ck_silver_procurement_record_index",
    "ck_silver_procurement_uf",
    "ck_silver_procurement_values",
}


@pytest.mark.integration
def test_silver_migration_creates_constraints_and_downgrades_cleanly(
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

    config = Config("alembic.ini")
    engine = create_engine(database_url, pool_pre_ping=True)
    command.upgrade(config, "head")

    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names(schema="silver")) >= {
            "procurement",
            "rejected_record",
        }
        assert inspector.get_pk_constraint("procurement", schema="silver")[
            "constrained_columns"
        ] == ["numero_controle_pncp"]

        procurement_checks = {
            item["name"]
            for item in inspector.get_check_constraints("procurement", schema="silver")
        }
        assert procurement_checks >= PROCUREMENT_CHECKS

        procurement_fk = inspector.get_foreign_keys("procurement", schema="silver")[0]
        assert procurement_fk["constrained_columns"] == ["source_raw_response_id"]
        assert procurement_fk["referred_schema"] == "bronze"
        assert procurement_fk["referred_table"] == "raw_api_response"
        assert procurement_fk["referred_columns"] == ["id"]

        rejected_columns = {
            column["name"]
            for column in inspector.get_columns("rejected_record", schema="silver")
        }
        assert rejected_columns >= {
            "source_raw_response_id",
            "source_record_index",
            "error_codes",
        }
        rejected_uniques = inspector.get_unique_constraints(
            "rejected_record", schema="silver"
        )
        assert any(
            item["column_names"] == ["source_raw_response_id", "source_record_index"]
            for item in rejected_uniques
        )
        rejected_fk = inspector.get_foreign_keys("rejected_record", schema="silver")[0]
        assert rejected_fk["referred_schema"] == "bronze"
        assert rejected_fk["referred_table"] == "raw_api_response"

        command.downgrade(config, "20260817_0002")
        downgraded = inspect(engine)
        assert set(downgraded.get_table_names(schema="silver")).isdisjoint(
            {"procurement", "rejected_record"}
        )
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()
