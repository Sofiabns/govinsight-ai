import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
from govinsight.config import get_settings

ANALYTICS_VIEWS = {
    "analytics_procurement_base",
    "analytics_summary",
    "analytics_by_organization",
    "analytics_by_state",
    "analytics_by_modality",
    "analytics_monthly",
}


@pytest.mark.integration
def test_analytics_migration_creates_reversible_metric_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch missing analytics contracts and downgrade dependency-order regressions."""
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for analytics migration tests")

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
        assert ANALYTICS_VIEWS <= set(inspector.get_view_names(schema="gold"))
        base_columns = {
            column["name"]
            for column in inspector.get_columns("analytics_procurement_base", schema="gold")
        }
        assert {
            "numero_controle_pncp",
            "publication_date",
            "organization_key",
            "uf_sigla",
            "modality_key",
            "valor_total_estimado",
            "valor_total_homologado",
        } <= base_columns

        command.downgrade(config, "20260826_0005")
        assert ANALYTICS_VIEWS.isdisjoint(inspect(engine).get_view_names(schema="gold"))
    finally:
        command.upgrade(config, "head")
        engine.dispose()
        get_settings.cache_clear()
