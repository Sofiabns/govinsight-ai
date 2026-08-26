import os

import pytest
from alembic.config import Config
from sqlalchemy import Numeric, create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from govinsight.config import get_settings

GOLD_TABLES = {
    "dim_date",
    "dim_organization",
    "dim_unit",
    "dim_modality",
    "fact_procurement",
}
FACT_FOREIGN_KEYS = {
    "fk_gold_fact_organization",
    "fk_gold_fact_unit",
    "fk_gold_fact_modality",
    "fk_gold_fact_publication_date",
    "fk_gold_fact_opening_date",
    "fk_gold_fact_closing_date",
    "fk_gold_fact_raw",
}
FACT_INDEXES = {
    "ix_gold_fact_organization",
    "ix_gold_fact_unit",
    "ix_gold_fact_modality",
    "ix_gold_fact_publication_date",
    "ix_gold_fact_year",
}


@pytest.mark.integration
def test_warehouse_migration_is_dimensional_constrained_and_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch missing Gold relations, weak keys, wrong money types, and unsafe downgrade order."""
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
        assert GOLD_TABLES <= set(inspector.get_table_names(schema="gold"))

        assert inspector.get_pk_constraint("dim_date", schema="gold")["constrained_columns"] == [
            "date_key"
        ]
        assert inspector.get_pk_constraint("fact_procurement", schema="gold")[
            "constrained_columns"
        ] == ["procurement_key"]

        organization_uniques = {
            item["name"]
            for item in inspector.get_unique_constraints("dim_organization", schema="gold")
        }
        unit_uniques = {
            item["name"] for item in inspector.get_unique_constraints("dim_unit", schema="gold")
        }
        modality_uniques = {
            item["name"] for item in inspector.get_unique_constraints("dim_modality", schema="gold")
        }
        fact_uniques = {
            item["name"]
            for item in inspector.get_unique_constraints("fact_procurement", schema="gold")
        }
        assert "uq_gold_dim_organization_cnpj" in organization_uniques
        assert "uq_gold_dim_unit_natural" in unit_uniques
        assert "uq_gold_dim_modality_id" in modality_uniques
        assert "uq_gold_fact_procurement_pncp" in fact_uniques

        assert {
            item["name"] for item in inspector.get_foreign_keys("fact_procurement", schema="gold")
        } >= FACT_FOREIGN_KEYS
        assert {
            item["name"] for item in inspector.get_indexes("fact_procurement", schema="gold")
        } >= FACT_INDEXES

        columns = {
            column["name"]: column
            for column in inspector.get_columns("fact_procurement", schema="gold")
        }
        for name in ("valor_total_estimado", "valor_total_homologado"):
            money_type = columns[name]["type"]
            assert isinstance(money_type, Numeric)
            assert money_type.precision == 19
            assert money_type.scale == 4
            assert columns[name]["nullable"] is True

        command.downgrade(config, "20260826_0004")
        downgraded = inspect(engine)
        assert GOLD_TABLES.isdisjoint(downgraded.get_table_names(schema="gold"))
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()
