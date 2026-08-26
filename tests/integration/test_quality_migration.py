import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from govinsight.config import get_settings

RUN_COLUMNS = {
    "id",
    "dataset",
    "stage",
    "source_watermark",
    "status",
    "started_at",
    "finished_at",
    "rows_evaluated",
    "score",
    "blocking_failures",
    "error_code",
}
RUN_CHECKS = {
    "ck_quality_run_counts",
    "ck_quality_run_score",
    "ck_quality_run_status",
}
RESULT_CHECKS = {
    "ck_quality_result_counts",
    "ck_quality_result_score",
    "ck_quality_result_status",
}


@pytest.mark.integration
def test_quality_migration_is_constrained_and_reversible(
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
        assert {"data_quality_run", "data_quality_result"} <= set(
            inspector.get_table_names(schema="control")
        )
        assert {
            column["name"] for column in inspector.get_columns("data_quality_run", schema="control")
        } >= RUN_COLUMNS
        assert {
            item["name"]
            for item in inspector.get_check_constraints("data_quality_run", schema="control")
        } >= RUN_CHECKS
        assert any(
            set(item["column_names"]) == {"dataset", "source_watermark"}
            for item in inspector.get_unique_constraints("data_quality_run", schema="control")
        )

        assert {
            item["name"]
            for item in inspector.get_check_constraints("data_quality_result", schema="control")
        } >= RESULT_CHECKS
        assert any(
            set(item["column_names"]) == {"run_id", "rule_code"}
            for item in inspector.get_unique_constraints("data_quality_result", schema="control")
        )
        result_fk = inspector.get_foreign_keys("data_quality_result", schema="control")[0]
        assert result_fk["constrained_columns"] == ["run_id"]
        assert result_fk["referred_schema"] == "control"
        assert result_fk["referred_table"] == "data_quality_run"
        assert result_fk["referred_columns"] == ["id"]
        assert result_fk["options"] == {"ondelete": "CASCADE"}

        command.downgrade(config, "20260823_0003")
        downgraded = inspect(engine)
        assert set(downgraded.get_table_names(schema="control")).isdisjoint(
            {"data_quality_run", "data_quality_result"}
        )
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()
