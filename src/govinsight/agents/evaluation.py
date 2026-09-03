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


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    cases: int
    accuracy: float = Field(ge=0, le=1)
    grounded_answer_rate: float = Field(ge=0, le=1)
    failure_rate: float = Field(ge=0, le=1)


def evaluate(cases: list[BenchmarkCase]) -> EvaluationResult:
    generator = RuleBasedSQLGenerator()
    guard = SafeSQLGuard()
    correct = grounded = failures = 0
    answerable = sum(not case.expected_blocked for case in cases)
    for case in cases:
        try:
            query = generator.generate(case.question)
            safe_sql = guard.validate(query.sql)
            if case.expected_blocked:
                failures += 1
                continue
            relation_matches = (
                case.expected_relation is None or case.expected_relation in safe_sql
            )
            if query.intent == case.expected_intent and relation_matches:
                correct += 1
            grounded += 1
        except ValueError:
            if case.expected_blocked:
                correct += 1
            else:
                failures += 1
    total = len(cases)
    return EvaluationResult(
        cases=total,
        accuracy=correct / total if total else 0,
        grounded_answer_rate=grounded / answerable if answerable else 0,
        failure_rate=failures / total if total else 0,
    )


def load_benchmark(path: Path) -> list[BenchmarkCase]:
    return [BenchmarkCase.model_validate(item) for item in json.loads(path.read_text("utf-8"))]


if __name__ == "__main__":
    benchmark_path = Path(sys.argv[1])
    print(evaluate(load_benchmark(benchmark_path)).model_dump_json(indent=2))
