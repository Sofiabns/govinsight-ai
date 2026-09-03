from pydantic import BaseModel, ConfigDict

from govinsight.analytics import AnalyticsSummary
from govinsight.quality import DataQualityRunResult
from govinsight.raw import IngestionResult
from govinsight.transform import TransformationResult
from govinsight.warehouse import WarehouseLoadResult


class PipelineRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: IngestionResult
    silver: TransformationResult
    quality: DataQualityRunResult
    warehouse: WarehouseLoadResult
    analytics: AnalyticsSummary


class PipelineStageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


__all__ = ["PipelineRunResult", "PipelineStageError"]
