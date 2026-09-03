from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from govinsight.analytics import (
    AnalyticsFilters,
    AnalyticsSummary,
    RankingRow,
)
from govinsight.api.main import create_app


class AnalyticsStub:
    def __init__(self) -> None:
        self.filters: list[AnalyticsFilters] = []

    def summary(self, filters: AnalyticsFilters) -> AnalyticsSummary:
        self.filters.append(filters)
        return AnalyticsSummary(
            procurement_count=2,
            estimated_value_count=2,
            estimated_total=Decimal("200"),
            estimated_average=Decimal("100"),
            homologated_value_count=1,
            homologated_total=Decimal("90"),
            homologated_average=Decimal("90"),
        )

    def rank(self, dimension, *, measure, filters, limit):
        self.filters.append(filters)
        return (
            RankingRow(
                rank=1,
                dimension=dimension,
                key="12345678000199",
                label="Órgão Exemplo",
                procurement_count=2,
                total=Decimal("90"),
                average=Decimal("45"),
                share=Decimal("1"),
            ),
        )


def test_analytics_api_exposes_summary_and_ranking_filters() -> None:
    """Catch API routes that drop validated filters or metric selections."""
    analytics = AnalyticsStub()
    app = create_app(database_check=lambda: True, analytics_service=analytics)

    with TestClient(app) as client:
        summary = client.get("/analytics/summary?start_date=2025-01-01&end_date=2025-01-31&uf=sp")
        ranking = client.get("/analytics/rankings/organization?measure=homologated&limit=5&uf=sp")

    assert summary.status_code == 200
    assert summary.json()["procurement_count"] == 2
    assert ranking.status_code == 200
    assert ranking.json()[0]["key"] == "12345678000199"
    assert analytics.filters == [
        AnalyticsFilters(start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), uf="SP"),
        AnalyticsFilters(uf="SP"),
    ]


def test_analytics_api_rejects_reversed_period_before_query() -> None:
    """Catch invalid date windows reaching the analytics service."""
    analytics = AnalyticsStub()
    app = create_app(database_check=lambda: True, analytics_service=analytics)

    with TestClient(app) as client:
        response = client.get("/analytics/summary?start_date=2025-02-01&end_date=2025-01-01")

    assert response.status_code == 422
    assert analytics.filters == []
