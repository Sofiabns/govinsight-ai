from fastapi.testclient import TestClient

from govinsight.api.main import create_app


def test_dashboard_is_available_from_application_root() -> None:
    app = create_app(database_check=lambda: True, analytics_service=None)

    with TestClient(app) as client:
        response = client.get("/", follow_redirects=True)

    assert response.status_code == 200
    assert "GovInsight AI — Compras públicas em perspectiva" in response.text
    assert 'id="filters"' in response.text
    assert 'id="agent-form"' in response.text
    assert response.text.count('class="prompt-chip"') == 4
    assert 'id="agent-result"' in response.text
    assert 'id="agent-evidence"' in response.text
