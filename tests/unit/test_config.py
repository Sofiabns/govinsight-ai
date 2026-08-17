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

