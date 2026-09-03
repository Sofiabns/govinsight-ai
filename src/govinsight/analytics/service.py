import structlog
from sqlalchemy import Engine

from govinsight.analytics.models import (
    AnalyticsFilters,
    AnalyticsSummary,
    DistributionSummary,
    Measure,
    MonthlyTrend,
    OutlierResult,
    OutlierRow,
    RankDimension,
    RankingRow,
)
from govinsight.analytics.repositories import AnalyticsRepository
from govinsight.analytics.statistics import describe, is_outlier

logger = structlog.get_logger(__name__)


class AnalyticsService:
    def __init__(self, engine: Engine, repository: AnalyticsRepository | None = None) -> None:
        self._engine = engine
        self._repository = repository or AnalyticsRepository()

    def summary(self, filters: AnalyticsFilters | None = None) -> AnalyticsSummary:
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            row = self._repository.summary(connection, selected)
        result = AnalyticsSummary(**row._mapping)
        logger.info(
            "analytics_summary_completed",
            filters=selected.model_dump(mode="json"),
            rows=result.procurement_count,
        )
        return result

    def rank(
        self,
        dimension: RankDimension,
        *,
        measure: Measure = Measure.HOMOLOGATED,
        filters: AnalyticsFilters | None = None,
        limit: int = 10,
    ) -> tuple[RankingRow, ...]:
        selected_dimension = RankDimension(dimension)
        selected_measure = Measure(measure)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.rank(
                connection, selected_dimension, selected_measure, selected, limit
            )
        result = tuple(
            RankingRow(rank=index, dimension=selected_dimension, **row._mapping)
            for index, row in enumerate(rows, start=1)
        )
        logger.info(
            "analytics_ranking_completed",
            dimension=selected_dimension,
            filters=selected.model_dump(mode="json"),
            rows=len(result),
        )
        return result

    def monthly_trend(self, filters: AnalyticsFilters | None = None) -> tuple[MonthlyTrend, ...]:
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.monthly(connection, selected)
        result = tuple(MonthlyTrend(**row._mapping) for row in rows)
        logger.info(
            "analytics_monthly_completed",
            filters=selected.model_dump(mode="json"),
            rows=len(result),
        )
        return result

    def distribution(
        self,
        measure: Measure = Measure.HOMOLOGATED,
        filters: AnalyticsFilters | None = None,
    ) -> DistributionSummary:
        selected_measure = Measure(measure)
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.values(connection, selected_measure, selected)
        result = describe([row.value for row in rows], selected_measure)
        logger.info(
            "analytics_distribution_completed",
            filters=selected.model_dump(mode="json"),
            sample_size=result.sample_size,
        )
        return result

    def outliers(
        self,
        measure: Measure = Measure.HOMOLOGATED,
        filters: AnalyticsFilters | None = None,
    ) -> OutlierResult:
        selected_measure = Measure(measure)
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.values(connection, selected_measure, selected)
        distribution = describe([row.value for row in rows], selected_measure)
        selected_rows = tuple(
            OutlierRow(numero_controle_pncp=row.numero_controle_pncp, value=row.value)
            for row in rows
            if is_outlier(row.value, distribution)
        )
        result = OutlierResult(distribution=distribution, outliers=selected_rows)
        logger.info(
            "analytics_outliers_completed",
            measure=selected_measure,
            filters=selected.model_dump(mode="json"),
            rows=len(selected_rows),
        )
        return result


__all__ = ["AnalyticsService"]
