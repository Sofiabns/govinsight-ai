from typing import Protocol

import structlog

from govinsight.analytics import AnalyticsSummary
from govinsight.extract.pncp.models import ProcurementQuery
from govinsight.orchestration.models import PipelineRunResult, PipelineStageError
from govinsight.quality import DataQualityRunResult, QualityRunStatus
from govinsight.raw import IngestionResult
from govinsight.transform import TransformationResult
from govinsight.warehouse import WarehouseLoadResult

logger = structlog.get_logger(__name__)


class RawStage(Protocol):
    def ingest_procurements(self, query: ProcurementQuery) -> IngestionResult: ...


class SilverStage(Protocol):
    def transform_pending(self, limit: int = 100) -> TransformationResult: ...


class QualityStage(Protocol):
    def run_pending(self) -> DataQualityRunResult: ...


class WarehouseStage(Protocol):
    def run_pending(self) -> WarehouseLoadResult: ...


class AnalyticsStage(Protocol):
    def summary(self) -> AnalyticsSummary: ...


class PipelineService:
    def __init__(
        self,
        raw: RawStage,
        silver: SilverStage,
        quality: QualityStage,
        warehouse: WarehouseStage,
        analytics: AnalyticsStage,
    ) -> None:
        self._raw = raw
        self._silver = silver
        self._quality = quality
        self._warehouse = warehouse
        self._analytics = analytics

    def run(self, query: ProcurementQuery, *, silver_batch_size: int = 100) -> PipelineRunResult:
        if silver_batch_size <= 0:
            raise ValueError("silver_batch_size must be positive")

        raw_result = self._raw.ingest_procurements(query)
        silver_result = self._transform_all(silver_batch_size)
        quality_result = self._quality.run_pending()
        if quality_result.status not in {QualityRunStatus.PASSED, QualityRunStatus.NOOP}:
            raise PipelineStageError("QUALITY_GATE_FAILED")
        warehouse_result = self._warehouse.run_pending()
        analytics_result = self._analytics.summary()
        result = PipelineRunResult(
            raw=raw_result,
            silver=silver_result,
            quality=quality_result,
            warehouse=warehouse_result,
            analytics=analytics_result,
        )
        logger.info(
            "pipeline_completed",
            raw_records=raw_result.records_received,
            silver_records=silver_result.records_received,
            quality_status=quality_result.status,
            gold_rows=warehouse_result.rows_loaded,
            analytics_rows=analytics_result.procurement_count,
        )
        return result

    def _transform_all(self, batch_size: int) -> TransformationResult:
        totals = {
            "responses_processed": 0,
            "records_received": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "rejected": 0,
        }
        last_raw_response_id = 0
        while True:
            batch = self._silver.transform_pending(limit=batch_size)
            last_raw_response_id = max(last_raw_response_id, batch.last_raw_response_id)
            if batch.responses_processed == 0:
                break
            for key in totals:
                totals[key] += getattr(batch, key)
        return TransformationResult(
            **totals,
            last_raw_response_id=last_raw_response_id,
        )


__all__ = ["PipelineService"]
