from sqlalchemy import create_engine

from govinsight.database.session import check_database


def test_check_database_executes_a_real_round_trip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    try:
        assert check_database(engine) is True
    finally:
        engine.dispose()
