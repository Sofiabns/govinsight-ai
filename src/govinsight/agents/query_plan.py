import re
from datetime import date
from enum import StrEnum
from typing import Annotated, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from govinsight.agents.data_agent import GeneratedQuery
from govinsight.analytics import Measure, RankDimension


class QueryIntent(StrEnum):
    SUMMARY = "summary"
    RANKING = "ranking"
    MONTHLY_TREND = "monthly_trend"
    DISTRIBUTION = "distribution"
    OUTLIERS = "outliers"


UNSAFE_QUESTION_TERMS = (
    "ignore",
    "system prompt",
    "instruções anteriores",
    "instrucoes anteriores",
    "union select",
    "credencial",
    "senha",
    "drop ",
    "delete ",
    "update ",
    "sql",
)


def validate_question_scope(question: str) -> None:
    normalized = question.casefold()
    if any(term in normalized for term in UNSAFE_QUESTION_TERMS):
        raise ValueError("unsafe instruction in question")
    if any(term in normalized for term in ("fornecedor", "categoria", "fraude")):
        raise ValueError("question is outside the supported analytical scope")


class QueryPlan(BaseModel):
    """Closed, serializable contract between language interpretation and SQL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: QueryIntent
    dimension: RankDimension | None = None
    measure: Measure = Measure.HOMOLOGATED
    start_date: date | None = None
    end_date: date | None = None
    uf: str | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 10

    @field_validator("uf")
    @classmethod
    def normalize_uf(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized != "UNKNOWN" and (len(normalized) != 2 or not normalized.isalpha()):
            raise ValueError("uf must contain two letters or UNKNOWN")
        return normalized

    @model_validator(mode="after")
    def validate_contract(self) -> "QueryPlan":
        if self.intent is QueryIntent.RANKING and self.dimension is None:
            raise ValueError("ranking requires a dimension")
        if self.intent is not QueryIntent.RANKING and self.dimension is not None:
            raise ValueError("dimension is only supported for ranking")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class QueryPlanCompiler:
    """Compile trusted enum values into parameterized, read-only SQL."""

    _ranking_views: ClassVar[dict[RankDimension, tuple[str, str, str]]] = {
        RankDimension.ORGANIZATION: (
            "analytics_by_organization",
            "orgao_razao_social",
            "orgao_cnpj",
        ),
        RankDimension.STATE: ("analytics_by_state", "uf_nome", "uf_sigla"),
        RankDimension.MODALITY: ("analytics_by_modality", "modalidade_nome", "modalidade_id"),
    }
    _base_dimensions: ClassVar[dict[RankDimension, tuple[str, str]]] = {
        RankDimension.ORGANIZATION: ("orgao_razao_social", "orgao_cnpj"),
        RankDimension.STATE: ("uf_nome", "uf_sigla"),
        RankDimension.MODALITY: ("modalidade_nome", "modalidade_id"),
    }
    _measure_columns: ClassVar[dict[Measure, str]] = {
        Measure.ESTIMATED: "valor_total_estimado",
        Measure.HOMOLOGATED: "valor_total_homologado",
    }

    def compile(self, plan: QueryPlan) -> GeneratedQuery:
        if plan.intent is QueryIntent.SUMMARY:
            return self._summary(plan)
        if plan.intent is QueryIntent.RANKING:
            return self._ranking(plan)
        if plan.intent is QueryIntent.MONTHLY_TREND:
            return self._monthly(plan)
        if plan.intent is QueryIntent.DISTRIBUTION:
            return self._distribution(plan)
        return self._outliers(plan)

    @staticmethod
    def _filters(plan: QueryPlan, alias: str = "") -> tuple[str, dict[str, object]]:
        prefix = f"{alias}." if alias else ""
        clauses: list[str] = []
        parameters: dict[str, object] = {}
        for name, operator in (("start_date", ">="), ("end_date", "<=")):
            value = getattr(plan, name)
            if value is not None:
                clauses.append(f"{prefix}publication_date {operator} :{name}")
                parameters[name] = value
        if plan.uf is not None:
            clauses.append(f"COALESCE({prefix}uf_sigla, 'UNKNOWN') = :uf")
            parameters["uf"] = plan.uf
        return (" WHERE " + " AND ".join(clauses) if clauses else "", parameters)

    def _summary(self, plan: QueryPlan) -> GeneratedQuery:
        filters, parameters = self._filters(plan)
        if not filters:
            sql = (
                "SELECT procurement_count, estimated_total, estimated_average, "
                "homologated_total, homologated_average "
                "FROM gold.analytics_summary LIMIT 1"
            )
        else:
            sql = (
                "SELECT COUNT(*) AS procurement_count, "
                "SUM(valor_total_estimado) AS estimated_total, "
                "AVG(valor_total_estimado) AS estimated_average, "
                "SUM(valor_total_homologado) AS homologated_total, "
                "AVG(valor_total_homologado) AS homologated_average "
                f"FROM gold.analytics_procurement_base{filters} LIMIT 1"
            )
        return GeneratedQuery(intent=plan.intent.value, sql=sql, parameters=parameters)

    def _ranking(self, plan: QueryPlan) -> GeneratedQuery:
        assert plan.dimension is not None
        measure = f"{plan.measure.value}_total"
        filters, parameters = self._filters(plan)
        if not filters:
            view, label, key = self._ranking_views[plan.dimension]
            sql = (
                f"SELECT {label} AS label, procurement_count, estimated_total, "
                f"homologated_total FROM gold.{view} "
                f"ORDER BY {measure} DESC NULLS LAST, {key} ASC LIMIT {plan.limit}"
            )
        else:
            label, key = self._base_dimensions[plan.dimension]
            value = self._measure_columns[plan.measure]
            sql = (
                f"SELECT {label} AS label, COUNT(*) AS procurement_count, "
                f"SUM({value}) AS {measure} FROM gold.analytics_procurement_base{filters} "
                f"GROUP BY {label}, {key} "
                f"ORDER BY {measure} DESC NULLS LAST, {key} ASC LIMIT {plan.limit}"
            )
        return GeneratedQuery(
            intent=f"ranking_{plan.dimension.value}", sql=sql, parameters=parameters
        )

    def _monthly(self, plan: QueryPlan) -> GeneratedQuery:
        filters, parameters = self._filters(plan)
        if not filters:
            sql = (
                "SELECT month, procurement_count, estimated_total, homologated_total, "
                "estimated_growth_rate, homologated_growth_rate "
                "FROM gold.analytics_monthly ORDER BY month LIMIT 200"
            )
        else:
            sql = (
                "SELECT CAST(date_trunc('month', publication_date) AS date) AS month, "
                "COUNT(*) AS procurement_count, SUM(valor_total_estimado) AS estimated_total, "
                "SUM(valor_total_homologado) AS homologated_total "
                f"FROM gold.analytics_procurement_base{filters} GROUP BY month "
                "ORDER BY month LIMIT 200"
            )
        return GeneratedQuery(intent=plan.intent.value, sql=sql, parameters=parameters)

    def _distribution(self, plan: QueryPlan) -> GeneratedQuery:
        value = self._measure_columns[plan.measure]
        filters, parameters = self._filters(plan)
        connector = " AND " if filters else " WHERE "
        sql = (
            f"SELECT COUNT({value}) AS sample_size, MIN({value}) AS minimum, "
            f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {value}) AS q1, "
            f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {value}) AS median, "
            f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {value}) AS q3, "
            f"MAX({value}) AS maximum, AVG({value}) AS mean "
            f"FROM gold.analytics_procurement_base{filters}{connector}{value} IS NOT NULL LIMIT 1"
        )
        return GeneratedQuery(intent=plan.intent.value, sql=sql, parameters=parameters)

    def _outliers(self, plan: QueryPlan) -> GeneratedQuery:
        value = self._measure_columns[plan.measure]
        filters, parameters = self._filters(plan, "b")
        stats_filters, _ = self._filters(plan, "s")
        connector = " AND " if filters else " WHERE "
        sql = (
            f"SELECT b.numero_controle_pncp, b.{value} AS value "
            "FROM gold.analytics_procurement_base b CROSS JOIN ("
            f"SELECT percentile_cont(0.25) WITHIN GROUP (ORDER BY {value}) AS q1, "
            f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {value}) AS q3 "
            f"FROM gold.analytics_procurement_base s{stats_filters}) stats"
            f"{filters}{connector}b.{value} IS NOT NULL "
            f"AND (b.{value} < stats.q1 - 1.5 * (stats.q3 - stats.q1) "
            f"OR b.{value} > stats.q3 + 1.5 * (stats.q3 - stats.q1)) "
            f"ORDER BY b.{value} DESC, b.numero_controle_pncp ASC LIMIT {plan.limit}"
        )
        return GeneratedQuery(intent=plan.intent.value, sql=sql, parameters=parameters)


__all__ = ["QueryIntent", "QueryPlan", "QueryPlanCompiler"]


class QueryPlanner(Protocol):
    def plan(self, question: str) -> QueryPlan: ...


class RuleBasedQueryPlanner:
    """Fast, auditable baseline for the public demo and provider fallback."""

    _brazilian_ufs: ClassVar[set[str]] = {
        "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt",
        "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro",
        "rr", "sc", "sp", "se", "to",
    }

    def plan(self, question: str) -> QueryPlan:
        normalized = question.casefold()
        validate_question_scope(question)
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", normalized)
        uf_match = re.search(
            r"(?:\buf\s+|\b(?:em|no|na|de|do|da)\s+(?:uf\s+)?)([a-z]{2})\b",
            normalized,
        )
        uf = uf_match.group(1) if uf_match and uf_match.group(1) in self._brazilian_ufs else None
        measure = Measure.ESTIMATED if "estimad" in normalized else Measure.HOMOLOGATED
        filters = {
            "measure": measure,
            "start_date": dates[0] if dates else None,
            "end_date": dates[1] if len(dates) > 1 else None,
            "uf": uf,
        }
        outlier_terms = (
            "atíp", "atip", "outlier", "fora do padrão", "maior valor",
            "maior compra", "maiores compras", "valores extremos",
        )
        if any(word in normalized for word in outlier_terms):
            return QueryPlan(intent=QueryIntent.OUTLIERS, **filters)
        distribution_terms = ("distribuição", "distribuicao", "mediana", "quartil")
        if any(word in normalized for word in distribution_terms):
            return QueryPlan(intent=QueryIntent.DISTRIBUTION, **filters)
        trend_terms = (
            "mensal", "mês", "evolução", "tendência", "ao longo do tempo",
            "mudaram", "variação", "variacao", "histórico", "historico",
        )
        if any(word in normalized for word in trend_terms):
            return QueryPlan(intent=QueryIntent.MONTHLY_TREND, **filters)
        dimensions = {
            "estado": RankDimension.STATE,
            "estados": RankDimension.STATE,
            "por uf": RankDimension.STATE,
            "modalidade": RankDimension.MODALITY,
            "órgão": RankDimension.ORGANIZATION,
            "orgao": RankDimension.ORGANIZATION,
            "quem mais compra": RankDimension.ORGANIZATION,
            "quem compra mais": RankDimension.ORGANIZATION,
            "compradores": RankDimension.ORGANIZATION,
        }
        for keyword, dimension in dimensions.items():
            if keyword in normalized:
                return QueryPlan(intent=QueryIntent.RANKING, dimension=dimension, **filters)
        return QueryPlan(intent=QueryIntent.SUMMARY, **filters)


class QueryPlanSQLGenerator:
    def __init__(self, planner: QueryPlanner, compiler: QueryPlanCompiler | None = None) -> None:
        self._planner = planner
        self._compiler = compiler or QueryPlanCompiler()

    def generate(self, question: str) -> GeneratedQuery:
        return self._compiler.compile(self._planner.plan(question))


__all__ = [
    "QueryIntent",
    "QueryPlan",
    "QueryPlanCompiler",
    "QueryPlanSQLGenerator",
    "QueryPlanner",
    "RuleBasedQueryPlanner",
    "validate_question_scope",
]
