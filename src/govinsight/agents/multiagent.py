from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from govinsight.agents.data_agent import AgentAnswer, QueryEvidence


class StatisticalResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    metrics: dict[str, Any]
    findings: list[str]


class QualityReview(BaseModel):
    model_config = ConfigDict(frozen=True)
    approved: bool
    issues: list[str]


class CriticReview(BaseModel):
    model_config = ConfigDict(frozen=True)
    approved: bool
    issues: list[str]
    required_corrections: list[str]


class ExecutiveReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str
    summary: str
    key_numbers: dict[str, Any]
    trends: list[str]
    opportunities: list[str]
    attention_points: list[str]
    evidence: list[QueryEvidence]
    verification: CriticReview


class DataAgentReader(Protocol):
    def ask(self, question: str) -> AgentAnswer: ...


class StatisticalAnalystAgent:
    def analyze(self, data: AgentAnswer) -> StatisticalResult:
        findings: list[str] = []
        if len(data.tables) > 1:
            findings.append(f"A consulta retornou {len(data.tables)} grupos comparáveis.")
        if data.tables and "month" in data.tables[-1]:
            findings.append("A série está ordenada por mês e preserva as taxas calculadas na Gold.")
        return StatisticalResult(metrics=data.metrics, findings=findings)


class BusinessInsightAgent:
    def interpret(self, data: AgentAnswer, statistics: StatisticalResult) -> list[str]:
        if not data.tables:
            return []
        if len(data.tables) > 1:
            return ["Os primeiros grupos concentram os maiores valores no recorte consultado."]
        return ["O resultado resume o recorte disponível na camada analítica validada."]


class DataQualityAgent:
    def review(self, data: AgentAnswer) -> QualityReview:
        issues = [] if data.tables else ["Não existem registros no recorte solicitado."]
        return QualityReview(approved=not issues, issues=issues)


class VerificationAgent:
    def verify(
        self,
        data: AgentAnswer,
        statistics: StatisticalResult,
        insights: list[str],
        quality: QualityReview,
    ) -> CriticReview:
        issues = list(quality.issues)
        if not data.evidence:
            issues.append("A resposta não contém evidência SQL.")
        if statistics.metrics != data.metrics:
            issues.append("Os números foram alterados durante a análise.")
        return CriticReview(
            approved=not issues,
            issues=issues,
            required_corrections=issues.copy(),
        )


class ExecutiveReportAgent:
    def compose(
        self,
        data: AgentAnswer,
        statistics: StatisticalResult,
        insights: list[str],
        critic: CriticReview,
    ) -> ExecutiveReport:
        if not critic.approved:
            raise ValueError("critic rejected the report")
        return ExecutiveReport(
            question=data.question,
            summary="Análise concluída exclusivamente com dados disponíveis na camada Gold.",
            key_numbers=statistics.metrics,
            trends=statistics.findings,
            opportunities=insights,
            attention_points=["Anomalias estatísticas não representam indício de fraude."],
            evidence=data.evidence,
            verification=critic,
        )


class MultiAgentCoordinator:
    def __init__(self, data_agent: DataAgentReader) -> None:
        self.data_agent = data_agent
        self.statistical_agent = StatisticalAnalystAgent()
        self.insight_agent = BusinessInsightAgent()
        self.quality_agent = DataQualityAgent()
        self.verification_agent = VerificationAgent()
        self.executive_agent = ExecutiveReportAgent()

    def run(self, question: str) -> ExecutiveReport:
        data = self.data_agent.ask(question)
        statistics = self.statistical_agent.analyze(data)
        insights = self.insight_agent.interpret(data, statistics)
        quality = self.quality_agent.review(data)
        critic = self.verification_agent.verify(data, statistics, insights, quality)
        return self.executive_agent.compose(data, statistics, insights, critic)


__all__ = [
    "CriticReview",
    "ExecutiveReport",
    "MultiAgentCoordinator",
]
