import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from govinsight.agents.data_agent import RuleBasedSQLGenerator, SafeSQLGuard


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str
    expected_answer: str
    expected_intent: str | None = None
    expected_relation: str | None = None
    expected_metric: str | None = None
    expected_blocked: bool = False
    expected_filters: dict[str, str] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    cases: int
    accuracy: float = Field(ge=0, le=1)
    grounded_answer_rate: float = Field(ge=0, le=1)
    failure_rate: float = Field(ge=0, le=1)
    intent_accuracy: float = Field(ge=0, le=1)
    filter_accuracy: float = Field(ge=0, le=1)
    safe_refusal_rate: float = Field(ge=0, le=1)
    unexpected_failure_rate: float = Field(ge=0, le=1)
    statuses: tuple[str, ...]


def evaluate(cases: list[BenchmarkCase]) -> EvaluationResult:
    generator = RuleBasedSQLGenerator()
    guard = SafeSQLGuard()
    correct = grounded = failures = intent_correct = filter_correct = refusals = 0
    answerable = sum(not case.expected_blocked for case in cases)
    filter_cases = sum(bool(case.expected_filters) for case in cases)
    blocked_cases = sum(case.expected_blocked for case in cases)
    statuses: list[str] = []
    for case in cases:
        try:
            query = generator.generate(case.question)
            safe_sql = guard.validate(query.sql)
            if case.expected_blocked:
                failures += 1
                statuses.append("unsafe_not_blocked")
                continue
            relation_matches = case.expected_relation is None or case.expected_relation in safe_sql
            intent_matches = query.intent == case.expected_intent
            if intent_matches:
                intent_correct += 1
            actual_filters = {
                key: value.isoformat() if hasattr(value, "isoformat") else str(value)
                for key, value in query.parameters.items()
            }
            filters_match = all(
                actual_filters.get(key) == value for key, value in case.expected_filters.items()
            )
            if case.expected_filters and filters_match:
                filter_correct += 1
            if intent_matches and relation_matches and filters_match:
                correct += 1
            grounded += 1
            passed = intent_matches and relation_matches and filters_match
            status = "passed" if passed else "mismatch"
            statuses.append(status)
        except ValueError:
            if case.expected_blocked:
                correct += 1
                refusals += 1
                statuses.append("safely_blocked")
            else:
                failures += 1
                statuses.append("unexpected_failure")
    total = len(cases)
    return EvaluationResult(
        cases=total,
        accuracy=correct / total if total else 0,
        grounded_answer_rate=grounded / answerable if answerable else 0,
        failure_rate=failures / total if total else 0,
        intent_accuracy=intent_correct / answerable if answerable else 0,
        filter_accuracy=filter_correct / filter_cases if filter_cases else 1,
        safe_refusal_rate=refusals / blocked_cases if blocked_cases else 1,
        unexpected_failure_rate=failures / total if total else 0,
        statuses=tuple(statuses),
    )


def load_benchmark(path: Path) -> list[BenchmarkCase]:
    return [BenchmarkCase.model_validate(item) for item in json.loads(path.read_text("utf-8"))]


if __name__ == "__main__":
    benchmark_path = Path(sys.argv[1])
    print(evaluate(load_benchmark(benchmark_path)).model_dump_json(indent=2))
