import pytest
from pydantic import ValidationError

from govinsight.config import Settings


def test_database_url_percent_encodes_credentials() -> None:
    settings = Settings(
        postgres_user="user@example.com",
        postgres_password="p@ss/word",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="govinsight",
    )

    assert settings.database_url == (
        "postgresql+psycopg://user%40example.com:p%40ss%2Fword@db:5432/govinsight"
    )


def test_settings_reject_non_positive_pool_size() -> None:
    with pytest.raises(ValidationError):
        Settings(postgres_pool_size=0)


def test_pncp_defaults_are_safe_for_the_official_api() -> None:
    settings = Settings()

    assert str(settings.pncp_base_url) == "https://pncp.gov.br/api/consulta"
    assert settings.pncp_timeout_seconds == 30.0
    assert settings.pncp_retry_max_attempts == 4
    assert settings.pncp_retry_base_delay_seconds == 0.5
    assert settings.pncp_retry_max_delay_seconds == 8.0


def test_openai_provider_requires_key_and_model() -> None:
    with pytest.raises(ValidationError):
        Settings(agent_provider="openai")

    settings = Settings(
        agent_provider="openai",
        openai_api_key="sk-test-secret",
        openai_model="gpt-test",
    )
    assert settings.agent_provider == "openai"
    assert "sk-test-secret" not in repr(settings)


def test_rules_provider_needs_no_external_key() -> None:
    settings = Settings(agent_provider="rules")

    assert settings.openai_api_key is None
    assert settings.agent_fallback_enabled is True


def test_complete_database_dsn_overrides_local_components_and_stays_secret() -> None:
    dsn = "postgresql+psycopg://reader:secret@managed.example/db?sslmode=require"
    settings = Settings(database_dsn=dsn)

    assert settings.database_url == dsn
    assert "secret" not in repr(settings)


def test_production_requires_managed_ssl_database_dsn() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production")
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            database_dsn="postgresql+psycopg://reader:secret@managed.example/db",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pncp_timeout_seconds", 0),
        ("pncp_retry_max_attempts", 0),
        ("pncp_retry_base_delay_seconds", 0),
        ("pncp_retry_max_delay_seconds", 0),
    ],
)
def test_pncp_settings_reject_non_positive_operational_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
