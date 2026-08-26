from sqlalchemy import Connection, Engine

from .models import (
    WarehouseLoadResult,
    WarehouseLoadStatus,
    WarehouseStateError,
    WarehouseWatermarkState,
)
from .repositories import WarehouseRepository, WarehouseWatermarkRepository


class WarehouseLoadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._watermarks = WarehouseWatermarkRepository()
        self._warehouse = WarehouseRepository()

    def run_pending(self) -> WarehouseLoadResult:
        with self._engine.connect() as connection:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                state = self._watermarks.read_state(connection, lock_gold=True)
                early_result = self._early_result(connection, state)
                if early_result is not None:
                    return early_result

                self._warehouse.load_dimensions(connection)
                rows_loaded = self._warehouse.load_facts(connection)
                reconciliation = self._warehouse.reconcile(connection)
                if not reconciliation.is_valid:
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
