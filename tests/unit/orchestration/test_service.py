from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

import govinsight.orchestration as orchestration
from govinsight.analytics import AnalyticsSummary
from govinsight.extract.pncp.models import ProcurementQuery
from govinsight.orchestration import PipelineService, PipelineStageError
from govinsight.quality import DataQualityRunResult, QualityRunStatus
from govinsight.raw import IngestionResult, RunStatus
from govinsight.transform import TransformationResult
from govinsight.warehouse import WarehouseLoadResult, WarehouseLoadStatus


def _query() -> ProcurementQuery:
    return ProcurementQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        modality_code=6,
        page=1,
        page_size=10,
    )


def _summary() -> AnalyticsSummary:
    return AnalyticsSummary(
        procurement_count=1,
        estimated_value_count=1,
        estimated_total=Decimal("100"),
        estimated_average=Decimal("100"),
        homologated_value_count=1,
        homologated_total=Decimal("90"),
        homologated_average=Decimal("90"),
    )


def test_scheduled_queries_cover_each_active_modality_with_update_overlap() -> None:
    build = getattr(orchestration, "build_scheduled_queries", None)
    assert callable(build), "orchestration must build scheduled PNCP queries"

    queries = build([8, 6, 8], today=date(2026, 9, 4), lookback_days=7)

    assert [(query.modality_code, query.start_date, query.end_date) for query in queries] == [
        (6, date(2026, 8, 29), date(2026, 9, 4)),
        (8, date(2026, 8, 29), date(2026, 9, 4)),
    ]
    assert all(query.mode.value == "atualizacao" for query in queries)
    assert all(query.page_size == 50 for query in queries)


def test_pipeline_runs_every_stage_in_order_until_analytics() -> None:
    """Catch reordered, skipped, or prematurely completed pipeline stages."""
    events: list[str] = []

    class Raw:
        def ingest_procurements(self, query: ProcurementQuery) -> IngestionResult:
            events.append("raw")
            return IngestionResult(
                run_id=uuid4(),
                status=RunStatus.SUCCEEDED,
                pages_processed=1,
                records_received=1,
                records_inserted=1,
                records_duplicate=0,
            )

    class Silver:
        calls = 0

        def transform_pending(self, limit: int) -> TransformationResult:
            events.append("silver")
            self.calls += 1
            return TransformationResult(
                responses_processed=1 if self.calls == 1 else 0,
                records_received=1 if self.calls == 1 else 0,
                inserted=1 if self.calls == 1 else 0,
                updated=0,
                unchanged=0,
                rejected=0,
                last_raw_response_id=10,
            )

    class Quality:
        def run_pending(self) -> DataQualityRunResult:
            events.append("quality")
            return DataQualityRunResult(
                run_id=1,
                source_watermark=10,
                status=QualityRunStatus.PASSED,
                rows_evaluated=1,
                score=Decimal("100"),
                blocking_failures=0,
            )

    class Warehouse:
        def run_pending(self) -> WarehouseLoadResult:
            events.append("warehouse")
            return WarehouseLoadResult(
                status=WarehouseLoadStatus.LOADED,
                source_watermark=10,
                rows_loaded=1,
            )

    class Analytics:
        def summary(self) -> AnalyticsSummary:
            events.append("analytics")
            return _summary()

    result = PipelineService(Raw(), Silver(), Quality(), Warehouse(), Analytics()).run(
        _query(), silver_batch_size=100
    )

    assert events == ["raw", "silver", "silver", "quality", "warehouse", "analytics"]
    assert result.analytics.procurement_count == 1
    assert result.silver.responses_processed == 1


def test_pipeline_stops_before_gold_when_quality_fails() -> None:
    """Catch publication of analytics from a quality-rejected snapshot."""
    events: list[str] = []

    class Stage:
        def ingest_procurements(self, query: ProcurementQuery) -> IngestionResult:
            events.append("raw")
            return IngestionResult(
                run_id=uuid4(),
                status=RunStatus.SUCCEEDED,
                pages_processed=0,
                records_received=0,
                records_inserted=0,
                records_duplicate=0,
            )

        def transform_pending(self, limit: int) -> TransformationResult:
            events.append("silver")
            return TransformationResult(
                responses_processed=0,
                records_received=0,
                inserted=0,
                updated=0,
                unchanged=0,
                rejected=0,
                last_raw_response_id=10,
            )

        def run_pending(self):
            events.append("quality")
            return DataQualityRunResult(
                run_id=2,
                source_watermark=10,
                status=QualityRunStatus.FAILED,
                rows_evaluated=1,
                score=Decimal("70"),
                blocking_failures=1,
            )

        def summary(self) -> AnalyticsSummary:
            events.append("analytics")
            return _summary()

    stage = Stage()
    with pytest.raises(PipelineStageError, match="QUALITY_GATE_FAILED"):
        PipelineService(stage, stage, stage, stage, stage).run(_query())

    assert events == ["raw", "silver", "quality"]
