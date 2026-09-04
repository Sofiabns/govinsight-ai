from datetime import date

import pytest
from pydantic import ValidationError

from govinsight.agents.query_plan import QueryIntent, QueryPlan, QueryPlanCompiler
from govinsight.analytics import Measure, RankDimension


def test_query_plan_normalizes_supported_filters() -> None:
    plan = QueryPlan(
        intent=QueryIntent.RANKING,
        dimension=RankDimension.STATE,
        measure=Measure.ESTIMATED,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        uf=" sp ",
        limit=25,
    )

    assert plan.uf == "SP"
    assert plan.limit == 25


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "ranking"},
        {"intent": "summary", "dimension": "state"},
        {"intent": "summary", "start_date": "2025-02-01", "end_date": "2025-01-01"},
        {"intent": "summary", "uf": "São Paulo"},
        {"intent": "summary", "limit": 101},
    ],
)
def test_query_plan_rejects_invalid_contracts(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        QueryPlan(**payload)


def test_compiler_parameterizes_filtered_summary() -> None:
    query = QueryPlanCompiler().compile(
        QueryPlan(
            intent="summary",
            start_date="2025-01-01",
            end_date="2025-01-31",
            uf="RJ",
        )
    )

    assert "gold.analytics_procurement_base" in query.sql
    assert ":start_date" in query.sql and ":end_date" in query.sql and ":uf" in query.sql
    assert "2025-01-01" not in query.sql and "RJ" not in query.sql
    assert query.parameters == {
        "start_date": date(2025, 1, 1),
        "end_date": date(2025, 1, 31),
        "uf": "RJ",
    }


@pytest.mark.parametrize(
    ("intent", "dimension", "expected"),
    [
        ("summary", None, "gold.analytics_summary"),
        ("ranking", "organization", "gold.analytics_by_organization"),
        ("ranking", "state", "gold.analytics_by_state"),
        ("ranking", "modality", "gold.analytics_by_modality"),
        ("monthly_trend", None, "gold.analytics_monthly"),
        ("distribution", None, "gold.analytics_procurement_base"),
        ("outliers", None, "gold.analytics_procurement_base"),
    ],
)
def test_compiler_uses_only_approved_views_and_bounded_limits(
    intent: str, dimension: str | None, expected: str
) -> None:
    query = QueryPlanCompiler().compile(QueryPlan(intent=intent, dimension=dimension, limit=10))

    assert expected in query.sql
    assert "LIMIT" in query.sql
    assert not query.parameters


def test_ranking_compiler_has_stable_tie_breaker() -> None:
    query = QueryPlanCompiler().compile(
        QueryPlan(intent="ranking", dimension="state", measure="homologated", limit=7)
    )

    assert "ORDER BY homologated_total DESC NULLS LAST, uf_sigla ASC" in query.sql
    assert query.sql.endswith("LIMIT 7")
