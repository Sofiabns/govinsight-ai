from types import SimpleNamespace

from fastapi.testclient import TestClient

from govinsight.api.main import create_app


class AgentStub:
    def ask(self, question: str):
        return {"question": question}


class ReportStub:
    def run(self, question: str):
        return {"question": question, "summary": "ok"}


def _client() -> TestClient:
    app = create_app(
        database_check=lambda: True,
        analytics_service=None,
        data_agent=AgentStub(),
        report_agent=ReportStub(),
    )
    return TestClient(app)


def test_agent_route_validates_question_body() -> None:
    with _client() as client:
        malformed = client.post("/agent/report", json={"question": "x"})
        oversized = client.post("/agent/report", json={"question": "x" * 501})

    assert malformed.status_code == 422
    assert oversized.status_code == 422


def test_agent_route_rate_limits_repeated_requests() -> None:
    with _client() as client:
        responses = [
            client.post("/agent/query", json={"question": "Mostre o resumo"}) for _ in range(21)
        ]

    assert responses[-1].status_code == 429
    assert responses[-1].headers["retry-after"]


def test_agent_timeout_has_safe_service_error() -> None:
    app = create_app(
        database_check=lambda: True,
        analytics_service=None,
        data_agent=SimpleNamespace(ask=lambda _question: (_ for _ in ()).throw(TimeoutError())),
    )
    with TestClient(app) as client:
        response = client.post("/agent/query", json={"question": "Mostre o resumo"})

    assert response.status_code == 503
    assert response.json() == {"detail": "agent timed out"}
