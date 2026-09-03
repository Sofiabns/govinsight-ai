from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from govinsight.agents import DataAgent, ReadOnlySQLExecutor, RuleBasedSQLGenerator
from govinsight.analytics import (
    AnalyticsFilters,
    AnalyticsService,
    Measure,
    RankDimension,
)
from govinsight.config import get_settings
from govinsight.database.session import check_database, create_database_engine
from govinsight.observability.logging import configure_logging, get_logger

DatabaseCheck = Callable[[], bool]


class AnalyticsReader(Protocol):
    def summary(self, filters: AnalyticsFilters): ...

    def rank(self, dimension: RankDimension, *, measure: Measure, filters, limit: int): ...

    def monthly_trend(self, filters: AnalyticsFilters): ...

    def distribution(self, measure: Measure, filters: AnalyticsFilters): ...

    def outliers(self, measure: Measure, filters: AnalyticsFilters): ...


class AgentReader(Protocol):
    def ask(self, question: str): ...


class AgentQuestion(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=500)]


def create_app(
    database_check: DatabaseCheck | None = None,
    analytics_service: AnalyticsReader | None = None,
    data_agent: AgentReader | None = None,
) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database_check is not None:
            app.state.database_check = database_check
            app.state.analytics = analytics_service
            app.state.data_agent = data_agent
            yield
            return

        engine = create_database_engine(settings)
        app.state.database_check = lambda: check_database(engine)
        app.state.analytics = AnalyticsService(engine)
        app.state.data_agent = DataAgent(
            RuleBasedSQLGenerator(),
            ReadOnlySQLExecutor(engine),
        )
        logger.info("database_engine_created", app_env=settings.app_env)
        try:
            yield
        finally:
            engine.dispose()
            logger.info("database_engine_disposed")

    application = FastAPI(
        title="GovInsight AI",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.get("/", include_in_schema=False)
    def dashboard_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/")

    def analytics_filters(
        start_date: date | None = None,
        end_date: date | None = None,
        organization_key: Annotated[int | None, Query(gt=0)] = None,
        uf: str | None = None,
        modality_key: Annotated[int | None, Query(gt=0)] = None,
    ) -> AnalyticsFilters:
        try:
            return AnalyticsFilters(
                start_date=start_date,
                end_date=end_date,
                organization_key=organization_key,
                uf=uf,
                modality_key=modality_key,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="invalid analytics filters") from exc

    @application.get("/health")
    def health(request: Request) -> dict[str, str]:
        try:
            database_is_ready = request.app.state.database_check()
        except SQLAlchemyError as exc:
            logger.warning("database_health_check_failed", error_type=type(exc).__name__)
            database_is_ready = False

        if not database_is_ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "unavailable", "database": "unreachable"},
            )

        return {"status": "ok", "database": "reachable"}

    Filters = Annotated[AnalyticsFilters, Depends(analytics_filters)]

    @application.get("/analytics/summary")
    def analytics_summary(request: Request, filters: Filters):
        return request.app.state.analytics.summary(filters)

    @application.get("/analytics/rankings/{dimension}")
    def analytics_ranking(
        request: Request,
        dimension: RankDimension,
        filters: Filters,
        measure: Measure = Measure.HOMOLOGATED,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ):
        return request.app.state.analytics.rank(
            dimension, measure=measure, filters=filters, limit=limit
        )

    @application.get("/analytics/trends")
    def analytics_trends(request: Request, filters: Filters):
        return request.app.state.analytics.monthly_trend(filters)

    @application.get("/analytics/distribution")
    def analytics_distribution(
        request: Request,
        filters: Filters,
        measure: Measure = Measure.HOMOLOGATED,
    ):
        return request.app.state.analytics.distribution(measure, filters)

    @application.get("/analytics/outliers")
    def analytics_outliers(
        request: Request,
        filters: Filters,
        measure: Measure = Measure.HOMOLOGATED,
    ):
        return request.app.state.analytics.outliers(measure, filters)

    @application.post("/agent/query")
    def agent_query(request: Request, payload: AgentQuestion):
        if request.app.state.data_agent is None:
            raise HTTPException(status_code=503, detail="data agent unavailable")
        try:
            return request.app.state.data_agent.ask(payload.question)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    dashboard_directory = Path(__file__).with_name("dashboard")
    application.mount(
        "/dashboard",
        StaticFiles(directory=dashboard_directory, html=True),
        name="dashboard",
    )

    return application


app = create_app()
