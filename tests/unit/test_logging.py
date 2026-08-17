import json

from govinsight.observability.logging import configure_logging, get_logger


def test_structured_log_contains_operational_context(capsys) -> None:
    configure_logging("INFO")
    logger = get_logger("test")

    logger.info(
        "pipeline_started",
        pipeline="setup",
        stage="health",
        records_processed=0,
    )

    event = json.loads(capsys.readouterr().out.strip())
    assert event["event"] == "pipeline_started"
    assert event["pipeline"] == "setup"
    assert event["stage"] == "health"
    assert event["records_processed"] == 0
    assert event["level"] == "info"
    assert event["timestamp"].endswith("Z")

