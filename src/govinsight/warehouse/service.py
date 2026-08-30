import sqlalchemy as sa
from sqlalchemy import Connection, Engine

from govinsight.observability.logging import get_logger

from .models import (
    WarehouseLoadResult,
    WarehouseLoadStatus,
    WarehouseStateError,
    WarehouseWatermarkState,
)
from .repositories import WarehouseRepository, WarehouseWatermarkRepository

WAREHOUSE_LOCK_KEY = "gold_procurement:procurements"


class WarehouseLoadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._watermarks = WarehouseWatermarkRepository()
        self._warehouse = WarehouseRepository()
        self._logger = get_logger(__name__)

    def run_pending(self) -> WarehouseLoadResult:
        with self._engine.connect() as connection:
            connection.execution_options(isolation_level="AUTOCOMMIT")
            connection.execute(
                sa.select(sa.func.pg_advisory_lock(sa.func.hashtext(WAREHOUSE_LOCK_KEY)))
            )
            connection.commit()
            try:
                connection.execution_options(isolation_level="REPEATABLE READ")
                result = self._run_transaction(connection)
                if result.status is WarehouseLoadStatus.LOADED:
                    self._logger.info(
                        "warehouse_load_completed",
                        source_watermark=result.source_watermark,
                        rows_loaded=result.rows_loaded,
                    )
                return result
            finally:
                if connection.in_transaction():
                    connection.rollback()
                connection.execution_options(isolation_level="AUTOCOMMIT")
                connection.execute(
                    sa.select(sa.func.pg_advisory_unlock(sa.func.hashtext(WAREHOUSE_LOCK_KEY)))
                )
                connection.commit()

    def _run_transaction(self, connection: Connection) -> WarehouseLoadResult:
        with connection.begin():
            state = self._watermarks.read_state(connection)
            self._logger.info(
                "warehouse_load_started",
                silver_watermark=state.silver,
                quality_watermark=state.quality,
                gold_watermark=state.gold,
            )
            early_result = self._early_result(connection, state)
            if early_result is not None:
                self._logger.info(
                    "warehouse_load_noop",
                    source_watermark=early_result.source_watermark,
                    rows_loaded=early_result.rows_loaded,
                )
                return early_result

            self._warehouse.load_dimensions(connection)
            rows_loaded = self._warehouse.load_facts(connection)
            reconciliation = self._warehouse.reconcile(connection)
            if not reconciliation.is_valid:
                self._logger.warning(
                    "warehouse_reconciliation_failed",
                    source_watermark=state.silver,
                    silver_rows=reconciliation.silver_rows,
                    fact_rows=reconciliation.fact_rows,
                    missing_in_fact=reconciliation.missing_in_fact,
                    missing_in_silver=reconciliation.missing_in_silver,
                    orphan_foreign_keys=reconciliation.orphan_foreign_keys,
                    lineage_mismatches=reconciliation.lineage_mismatches,
                )
                raise WarehouseStateError("RECONCILIATION_FAILED")

            self._watermarks.advance(connection, state.silver)
            return WarehouseLoadResult(
                status=WarehouseLoadStatus.LOADED,
                source_watermark=state.silver,
                rows_loaded=rows_loaded,
            )

    def _early_result(
        self,
        connection: Connection,
        state: WarehouseWatermarkState,
    ) -> WarehouseLoadResult | None:
        if state.silver == state.quality == state.gold == 0:
            return WarehouseLoadResult(
                status=WarehouseLoadStatus.NOOP,
                source_watermark=0,
                rows_loaded=0,
                reused=True,
            )
        if state.silver != state.quality:
            raise WarehouseStateError("UNAPPROVED_SILVER_SNAPSHOT")
        if state.gold > state.quality:
            raise WarehouseStateError("GOLD_WATERMARK_AHEAD")
        if state.gold == state.quality:
            return WarehouseLoadResult(
                status=WarehouseLoadStatus.NOOP,
                source_watermark=state.gold,
                rows_loaded=self._warehouse.fact_count(connection),
                reused=True,
            )
        return None


__all__ = ["WarehouseLoadService"]
