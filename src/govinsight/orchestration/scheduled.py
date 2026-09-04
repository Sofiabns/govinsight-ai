import argparse
import json
from datetime import date

from govinsight.analytics import AnalyticsService
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.extract.pncp.client import PNCPClient
from govinsight.orchestration.service import PipelineService, build_scheduled_queries
from govinsight.quality import DataQualityService
from govinsight.raw.service import RawIngestionService
from govinsight.transform import SilverTransformationService
from govinsight.warehouse import WarehouseLoadService


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize recent PNCP updates")
    parser.add_argument("--lookback-days", type=int, default=7)
    args = parser.parse_args()

    settings = Settings()
    engine = create_database_engine(settings)
    summaries: list[dict[str, object]] = []
    try:
        with PNCPClient.from_settings(settings) as client:
            pipeline = PipelineService(
                RawIngestionService(engine, client),
                SilverTransformationService(engine),
                DataQualityService(engine),
                WarehouseLoadService(engine),
                AnalyticsService(engine),
            )
            queries = build_scheduled_queries(
                client.list_active_modalities(),
                today=date.today(),
                lookback_days=args.lookback_days,
            )
            for query in queries:
                result = pipeline.run(query)
                summaries.append(
                    {
                        "modality_code": query.modality_code,
                        "records_received": result.raw.records_received,
                        "gold_rows_loaded": result.warehouse.rows_loaded,
                        "analytics_rows": result.analytics.procurement_count,
                    }
                )
        print(json.dumps({"status": "completed", "modalities": summaries}, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
