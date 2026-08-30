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
from govinsight.analytics.statistics import describe

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
        logger.info("analytics_summary_completed", filters=selected.model_dump(mode="json"))
        return result

    def rank(
        self,
        dimension: RankDimension,
        *,
        measure: Measure = Measure.HOMOLOGATED,
        filters: AnalyticsFilters | None = None,
        limit: int = 10,
    ) -> tuple[RankingRow, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.rank(connection, dimension, measure, selected, limit)
        result = tuple(
            RankingRow(rank=index, dimension=dimension, **row._mapping)
            for index, row in enumerate(rows, start=1)
        )
        logger.info("analytics_ranking_completed", dimension=dimension, rows=len(result))
        return result

    def monthly_trend(
        self, filters: AnalyticsFilters | None = None
    ) -> tuple[MonthlyTrend, ...]:
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.monthly(connection, selected)
        result = tuple(MonthlyTrend(**row._mapping) for row in rows)
        logger.info("analytics_monthly_completed", rows=len(result))
        return result

    def distribution(
        self, measure: Measure, filters: AnalyticsFilters | None = None
    ) -> DistributionSummary:
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.values(connection, measure, selected)
        return describe([row.value for row in rows], measure)

    def outliers(
        self, measure: Measure, filters: AnalyticsFilters | None = None
    ) -> OutlierResult:
        selected = filters or AnalyticsFilters()
        with self._engine.connect() as connection:
            rows = self._repository.values(connection, measure, selected)
        distribution = describe([row.value for row in rows], measure)
        if distribution.lower_fence is None or distribution.upper_fence is None:
            selected_rows = ()
        else:
            selected_rows = tuple(
                OutlierRow(numero_controle_pncp=row.numero_controle_pncp, value=row.value)
                for row in rows
                if row.value < distribution.lower_fence or row.value > distribution.upper_fence
            )
        result = OutlierResult(distribution=distribution, outliers=selected_rows)
        logger.info("analytics_outliers_completed", measure=measure, rows=len(selected_rows))
        return result


__all__ = ["AnalyticsService"]
