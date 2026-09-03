import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine, text


class GeneratedQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: str
    sql: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class QueryEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    sql: str
    row_count: int


class AgentAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    metrics: dict[str, Any]
    tables: list[dict[str, Any]]
    observations: list[str]
    evidence: list[QueryEvidence]


class SQLGenerator(Protocol):
    def generate(self, question: str) -> GeneratedQuery: ...


class SQLExecutor(Protocol):
    @contextmanager
    def execute(self, query: GeneratedQuery) -> Iterator[list[dict[str, Any]]]: ...


class SafeSQLGuard:
    """Conservative allow-list for agent-generated analytical SQL."""

    allowed_relations = frozenset(
        {
            "analytics_summary",
            "analytics_by_organization",
            "analytics_by_state",
            "analytics_by_modality",
            "analytics_monthly",
        }
    )
    forbidden = re.compile(
        r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|call|do|execute|pg_sleep)\b",
        re.IGNORECASE,
    )
    relations = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)

    def validate(self, sql: str) -> str:
        normalized = sql.strip().rstrip(";").strip()
        relation_names = {
            match.split(".")[-1].lower() for match in self.relations.findall(normalized)
        }
        safe = (
            bool(normalized)
            and normalized.lower().startswith("select ")
            and ";" not in normalized
            and "--" not in normalized
            and "/*" not in normalized
            and not self.forbidden.search(normalized)
            and bool(relation_names)
            and relation_names <= self.allowed_relations
        )
        if not safe:
            raise ValueError("agent must produce one safe analytical query")
        if re.search(r"\blimit\s+\d+\s*$", normalized, re.I):
            return normalized
        return f"{normalized} LIMIT 200"


class RuleBasedSQLGenerator:
    """Auditable natural-language baseline; an LLM can replace this protocol later."""

    def generate(self, question: str) -> GeneratedQuery:
        normalized = question.casefold()
        if any(
            term in normalized
            for term in ("ignore as instruções", "ignore instrucoes", "drop ", "delete ", "update ")
        ):
            raise ValueError("unsafe instruction in question")
        if any(word in normalized for word in ("mensal", "mês", "evolução", "tendência")):
            return GeneratedQuery(
                intent="monthly_trend",
                sql=(
                    "SELECT month, procurement_count, estimated_total, homologated_total, "
                    "estimated_growth_rate, homologated_growth_rate "
                    "FROM gold.analytics_monthly ORDER BY month"
                ),
            )
        dimensions = {
            "estado": ("state", "analytics_by_state", "uf_nome"),
            "uf": ("state", "analytics_by_state", "uf_nome"),
            "modalidade": ("modality", "analytics_by_modality", "modalidade_nome"),
            "órgão": ("organization", "analytics_by_organization", "orgao_razao_social"),
            "orgao": ("organization", "analytics_by_organization", "orgao_razao_social"),
        }
        for keyword, (intent, relation, label_column) in dimensions.items():
            if keyword in normalized:
                return GeneratedQuery(
                    intent=f"ranking_{intent}",
                    sql=(
                        f"SELECT {label_column} AS label, procurement_count, estimated_total, "
                        f"homologated_total FROM gold.{relation} "
                        "ORDER BY homologated_total DESC NULLS LAST LIMIT 10"
                    ),
                )
        return GeneratedQuery(
            intent="summary",
            sql=(
                "SELECT procurement_count, estimated_total, estimated_average, "
                "homologated_total, homologated_average FROM gold.analytics_summary"
            ),
        )


class ReadOnlySQLExecutor:
    def __init__(self, engine: Engine, guard: SafeSQLGuard | None = None) -> None:
        self._engine = engine
        self._guard = guard or SafeSQLGuard()

    @contextmanager
    def execute(self, query: GeneratedQuery) -> Iterator[list[dict[str, Any]]]:
        safe_sql = self._guard.validate(query.sql)
        with self._engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            result = connection.execute(text(safe_sql), query.parameters)
            yield [dict(row._mapping) for row in result]


class DataAgent:
    def __init__(self, generator: SQLGenerator, executor: SQLExecutor) -> None:
        self._generator = generator
        self._executor = executor

    def ask(self, question: str) -> AgentAnswer:
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("question cannot be empty")
        query = self._generator.generate(cleaned)
        with self._executor.execute(query) as rows:
            serialized = [_serialize_row(row) for row in rows]
        metrics = serialized[0] if len(serialized) == 1 else {"row_count": len(serialized)}
        observation = (
            "Consulta concluída com evidência disponível."
            if serialized
            else "Não há dados para responder à pergunta."
        )
        relation = SafeSQLGuard.relations.findall(query.sql)[0].split(".")[-1]
        return AgentAnswer(
            question=cleaned,
            metrics=metrics,
            tables=serialized,
            observations=[observation],
            evidence=[
                QueryEvidence(
                    source=f"gold.{relation}",
                    sql=query.sql,
                    row_count=len(serialized),
                )
            ],
        )


def _serialize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}


__all__: Sequence[str] = (
    "AgentAnswer",
    "DataAgent",
    "GeneratedQuery",
    "ReadOnlySQLExecutor",
    "RuleBasedSQLGenerator",
    "SafeSQLGuard",
)
