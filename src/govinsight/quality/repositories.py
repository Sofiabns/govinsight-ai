from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from govinsight.raw.tables import etl_watermark

from .models import (
    DataQualityRunResult,
    QualityDimension,
    QualityRunStatus,
    RuleEvaluation,
    RuleSeverity,
    RuleStatus,
)
from .tables import data_quality_result, data_quality_run

DATASET = "procurements"
QUALITY_PIPELINE = "data_quality"
QUALITY_STAGE = "quality"
SILVER_PIPELINE = "silver_procurement"
SILVER_STAGE = "silver"


class QualityStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class QualityRunState:
    run_id: int
    status: QualityRunStatus
    created: bool


def _watermark_key(pipeline: str, stage: str) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        etl_watermark.c.pipeline_name == pipeline,
        etl_watermark.c.dataset == DATASET,
        etl_watermark.c.stage == stage,
    )


def _read_watermark(
    connection: Connection,
    pipeline: str,
    stage: str,
    *,
    lock: bool = False,
) -> int:
    statement = sa.select(etl_watermark.c.watermark_value).where(*_watermark_key(pipeline, stage))
    if lock:
        statement = statement.with_for_update()
    row = connection.execute(statement).one_or_none()
    if row is None:
        return 0
    value = row.watermark_value
    raw_id = value.get("last_raw_response_id") if isinstance(value, dict) else None
    if not isinstance(raw_id, int) or raw_id < 0:
        raise QualityStateError("invalid quality watermark state")
    return raw_id


class QualityWatermarkRepository:
    def silver_current(self, connection: Connection) -> int:
        return _read_watermark(connection, SILVER_PIPELINE, SILVER_STAGE)

    def quality_current(self, connection: Connection, *, lock: bool = False) -> int:
        return _read_watermark(
            connection,
            QUALITY_PIPELINE,
            QUALITY_STAGE,
            lock=lock,
        )

    def advance(self, connection: Connection, raw_response_id: int) -> None:
        now = datetime.now(UTC)
        statement = postgresql.insert(etl_watermark).values(
            pipeline_name=QUALITY_PIPELINE,
            dataset=DATASET,
            stage=QUALITY_STAGE,
            watermark_value={"last_raw_response_id": raw_response_id},
            confirmed_at=now,
        )
        stored_id = sa.cast(
            etl_watermark.c.watermark_value["last_raw_response_id"].astext,
            sa.BigInteger(),
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    etl_watermark.c.pipeline_name,
                    etl_watermark.c.dataset,
                    etl_watermark.c.stage,
                ],
                set_={
                    "watermark_value": statement.excluded.watermark_value,
                    "confirmed_at": statement.excluded.confirmed_at,
                },
                where=stored_id < raw_response_id,
            )
        )


class QualityRunRepository:
    def start_or_get(self, connection: Connection, source_watermark: int) -> QualityRunState:
        statement = (
            postgresql.insert(data_quality_run)
            .values(
                dataset=DATASET,
                stage=QUALITY_STAGE,
                source_watermark=source_watermark,
                status=QualityRunStatus.RUNNING.value,
                started_at=datetime.now(UTC),
                rows_evaluated=0,
                blocking_failures=0,
            )
            .on_conflict_do_nothing(constraint="uq_quality_run_snapshot")
            .returning(data_quality_run.c.id)
        )
        run_id = connection.execute(statement).scalar_one_or_none()
        if run_id is not None:
            return QualityRunState(
                run_id=run_id,
                status=QualityRunStatus.RUNNING,
                created=True,
            )
        existing = connection.execute(
            sa.select(data_quality_run.c.id, data_quality_run.c.status)
            .where(
                data_quality_run.c.dataset == DATASET,
                data_quality_run.c.source_watermark == source_watermark,
            )
            .with_for_update()
        ).one()
        return QualityRunState(
            run_id=existing.id,
            status=QualityRunStatus(existing.status),
            created=False,
        )

    def complete(
        self,
        connection: Connection,
        run_id: int,
        result: DataQualityRunResult,
    ) -> None:
        connection.execute(
            data_quality_run.update()
            .where(data_quality_run.c.id == run_id)
            .values(
                status=result.status.value,
                finished_at=datetime.now(UTC),
                rows_evaluated=result.rows_evaluated,
                score=result.score,
                blocking_failures=result.blocking_failures,
                error_code=None,
            )
        )

    def fail_execution(self, connection: Connection, run_id: int, error_code: str) -> bool:
        result = connection.execute(
            data_quality_run.update()
            .where(
                data_quality_run.c.id == run_id,
                data_quality_run.c.status == QualityRunStatus.RUNNING.value,
            )
            .values(
                status=QualityRunStatus.FAILED.value,
                finished_at=datetime.now(UTC),
                error_code=error_code,
            )
        )
        return result.rowcount == 1

    def successful_row_counts(
        self,
        connection: Connection,
        limit: int = 10,
    ) -> tuple[int, ...]:
        values = connection.execute(
            sa.select(data_quality_run.c.rows_evaluated)
            .where(
                data_quality_run.c.dataset == DATASET,
                data_quality_run.c.status == QualityRunStatus.PASSED.value,
            )
            .order_by(data_quality_run.c.finished_at.desc())
            .limit(limit)
        ).scalars()
        return tuple(values)

    def load(self, connection: Connection, run_id: int) -> DataQualityRunResult:
        run = (
            connection.execute(sa.select(data_quality_run).where(data_quality_run.c.id == run_id))
            .mappings()
            .one()
        )
        evaluations = QualityResultRepository().for_run(connection, run_id)
        return DataQualityRunResult(
            run_id=run_id,
            source_watermark=run["source_watermark"],
            status=QualityRunStatus(run["status"]),
            rows_evaluated=run["rows_evaluated"],
            score=run["score"],
            blocking_failures=run["blocking_failures"],
            evaluations=evaluations,
            reused=True,
        )


class QualityResultRepository:
    @staticmethod
    def _safe_details(details: dict[str, int | str | Decimal]) -> dict[str, int | str]:
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in details.items()
        }

    def replace(
        self,
        connection: Connection,
        run_id: int,
        values: tuple[RuleEvaluation, ...],
    ) -> None:
        connection.execute(
            data_quality_result.delete().where(data_quality_result.c.run_id == run_id)
        )
        now = datetime.now(UTC)
        connection.execute(
            data_quality_result.insert(),
            [
                {
                    "run_id": run_id,
                    "rule_code": value.rule_code,
                    "dimension": value.dimension.value,
                    "severity": value.severity.value,
                    "status": value.status.value,
                    "checked_count": value.checked_count,
                    "failed_count": value.failed_count,
                    "score": value.score,
                    "details": self._safe_details(value.details),
                    "evaluated_at": now,
                }
                for value in values
            ],
        )

    def for_run(self, connection: Connection, run_id: int) -> tuple[RuleEvaluation, ...]:
        rows = connection.execute(
            sa.select(data_quality_result)
            .where(data_quality_result.c.run_id == run_id)
            .order_by(data_quality_result.c.id)
        ).mappings()
        return tuple(
            RuleEvaluation(
                rule_code=row["rule_code"],
                dimension=QualityDimension(row["dimension"]),
                severity=RuleSeverity(row["severity"]),
                status=RuleStatus(row["status"]),
                checked_count=row["checked_count"],
                failed_count=row["failed_count"],
                score=row["score"],
                details=row["details"],
            )
            for row in rows
        )


__all__ = [
    "QualityResultRepository",
    "QualityRunRepository",
    "QualityRunState",
    "QualityStateError",
    "QualityWatermarkRepository",
]
