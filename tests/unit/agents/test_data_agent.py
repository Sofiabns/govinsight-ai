from contextlib import contextmanager

import pytest

from govinsight.agents.data_agent import DataAgent, GeneratedQuery, SafeSQLGuard


class GeneratorStub:
    def generate(self, question: str) -> GeneratedQuery:
        return GeneratedQuery(
            intent="summary",
            sql="SELECT procurement_count FROM analytics_summary LIMIT 200",
        )


class ExecutorStub:
    @contextmanager
    def execute(self, query: GeneratedQuery):
        yield [{"procurement_count": 12}]


def test_data_agent_returns_structured_evidence() -> None:
    result = DataAgent(GeneratorStub(), ExecutorStub()).ask("Quantas compras foram analisadas?")

    assert result.question == "Quantas compras foram analisadas?"
    assert result.metrics == {"procurement_count": 12}
    assert result.evidence[0].row_count == 1
    assert result.evidence[0].source == "gold.analytics_summary"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM gold.fact_procurement",
        "SELECT * FROM analytics_summary; DROP TABLE gold.fact_procurement",
        "SELECT * FROM silver.procurement",
        "SELECT * FROM gold.analytics_summary LIMIT 201",
    ],
)
def test_sql_guard_rejects_unsafe_or_unapproved_queries(sql: str) -> None:
    with pytest.raises(ValueError, match="safe analytical query"):
        SafeSQLGuard().validate(sql)
