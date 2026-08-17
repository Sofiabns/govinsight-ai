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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pncp_timeout_seconds", 0),
        ("pncp_retry_max_attempts", 0),
        ("pncp_retry_base_delay_seconds", 0),
        ("pncp_retry_max_delay_seconds", 0),
    ],
)
def test_pncp_settings_reject_non_positive_operational_limits(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
