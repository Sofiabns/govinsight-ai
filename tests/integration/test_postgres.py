import os

import pytest
from sqlalchemy import create_engine

from govinsight.database.session import check_database


@pytest.mark.integration
def test_postgres_accepts_application_connection() -> None:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        assert check_database(engine) is True
    finally:
        engine.dispose()

