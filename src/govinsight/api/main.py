from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from govinsight.config import get_settings
from govinsight.database.session import check_database, create_database_engine
from govinsight.observability.logging import configure_logging, get_logger

DatabaseCheck = Callable[[], bool]


def create_app(database_check: DatabaseCheck | None = None) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database_check is not None:
            app.state.database_check = database_check
            yield
            return

        engine = create_database_engine(settings)
        app.state.database_check = lambda: check_database(engine)
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

    return application


app = create_app()
