from pathlib import Path

from govinsight.agents.evaluation import evaluate, load_benchmark


def test_agent_benchmark_meets_required_metrics() -> None:
    path = Path("tests/fixtures/agents/agent_evaluation.json")

    result = evaluate(load_benchmark(path))

    assert result.accuracy == 1.0
    assert result.grounded_answer_rate == 1.0
    assert result.failure_rate == 0.0
    assert result.intent_accuracy == 1.0
    assert result.filter_accuracy == 1.0
    assert result.safe_refusal_rate == 1.0
    assert result.unexpected_failure_rate == 0.0
    assert len(result.statuses) >= 30
