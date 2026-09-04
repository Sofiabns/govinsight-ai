import pytest

from govinsight.agents.data_agent import AgentAnswer, QueryEvidence
from govinsight.agents.multiagent import MultiAgentCoordinator


class DataAgentStub:
    def ask(self, question: str) -> AgentAnswer:
        return AgentAnswer(
            question=question,
            metrics={"procurement_count": 12},
            tables=[{"procurement_count": 12}],
            observations=[],
            evidence=[QueryEvidence(source="gold.analytics_summary", sql="SELECT 12", row_count=1)],
        )


def test_multiagent_report_preserves_evidence_and_numbers() -> None:
    report = MultiAgentCoordinator(DataAgentStub()).run("Quantas compras existem?")

    assert report.key_numbers == {"procurement_count": 12}
    assert report.data_points == [{"procurement_count": 12}]
    assert report.verification.approved is True
    assert report.evidence[0].source == "gold.analytics_summary"


class EmptyDataAgentStub:
    def ask(self, question: str) -> AgentAnswer:
        return AgentAnswer(
            question=question,
            metrics={"procurement_count": 0},
            tables=[{"procurement_count": 0}],
            observations=[],
            evidence=[QueryEvidence(source="gold.analytics_summary", sql="SELECT 0", row_count=1)],
        )


def test_multiagent_blocks_report_when_procurement_base_is_empty() -> None:
    with pytest.raises(ValueError, match="critic rejected"):
        MultiAgentCoordinator(EmptyDataAgentStub()).run("Quantas compras existem?")
