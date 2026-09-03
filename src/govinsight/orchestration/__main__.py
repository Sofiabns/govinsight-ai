import argparse
from datetime import date

from govinsight.analytics import AnalyticsService
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.models import ProcurementQuery
from govinsight.orchestration.service import PipelineService
from govinsight.quality import DataQualityService
from govinsight.raw.service import RawIngestionService
from govinsight.transform import SilverTransformationService
from govinsight.warehouse import WarehouseLoadService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GovInsight procurement pipeline")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--modality", required=True, type=int)
    parser.add_argument("--page-size", type=int, default=50)
    args = parser.parse_args()

    settings = Settings()
    engine = create_database_engine(settings)
    query = ProcurementQuery(
        start_date=args.start,
        end_date=args.end,
        modality_code=args.modality,
        page_size=args.page_size,
    )
    try:
        with PNCPClient.from_settings(settings) as client:
            result = PipelineService(
                RawIngestionService(engine, client),
                SilverTransformationService(engine),
                DataQualityService(engine),
                WarehouseLoadService(engine),
                AnalyticsService(engine),
            ).run(query)
        print(result.model_dump_json(indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
