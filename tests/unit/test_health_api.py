from fastapi.testclient import TestClient

from govinsight.api.main import create_app


def test_health_reports_database_ready() -> None:
    app = create_app(database_check=lambda: True)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


def test_health_blocks_readiness_when_database_is_unavailable() -> None:
    app = create_app(database_check=lambda: False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": {"status": "unavailable", "database": "unreachable"}}
