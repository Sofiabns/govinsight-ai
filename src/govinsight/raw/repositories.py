from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from .hashing import ParameterValue, scope_parameters
from .models import InsertOutcome, RawCapture, RawDataset, RunStatus
from .tables import etl_run, extraction_checkpoint, raw_api_response


class RawResponseRepository:
    def insert(self, connection: Connection, capture: RawCapture) -> InsertOutcome:
        statement = (
            postgresql.insert(raw_api_response)
            .values(capture.model_dump())
            .on_conflict_do_nothing(constraint="uq_raw_response_identity_body")
            .returning(raw_api_response.c.id)
        )
        raw_response_id = connection.execute(statement).scalar_one_or_none()
        return InsertOutcome(
            inserted=raw_response_id is not None,
            raw_response_id=raw_response_id,
        )


class RunRepository:
    def create(
        self,
        connection: Connection,
        pipeline_name: str,
        dataset: RawDataset,
        mode: str,
    ) -> UUID:
        run_id = uuid4()
        connection.execute(
            etl_run.insert().values(
                id=run_id,
                pipeline_name=pipeline_name,
                dataset=dataset.value,
                mode=mode,
                status=RunStatus.RUNNING.value,
                started_at=datetime.now(UTC),
                finished_at=None,
                pages_processed=0,
                records_received=0,
                records_inserted=0,
                records_duplicate=0,
                error_code=None,
            )
        )
        return run_id

    def apply_page(
        self,
        connection: Connection,
        run_id: UUID,
        record_count: int,
        inserted: bool,
    ) -> None:
        connection.execute(
            etl_run.update()
            .where(etl_run.c.id == run_id)
            .values(
                pages_processed=etl_run.c.pages_processed + 1,
                records_received=etl_run.c.records_received + record_count,
                records_inserted=etl_run.c.records_inserted + (record_count if inserted else 0),
                records_duplicate=etl_run.c.records_duplicate + (0 if inserted else record_count),
            )
        )

    def finish(
        self,
        connection: Connection,
        run_id: UUID,
        status: RunStatus,
        error_code: str | None = None,
    ) -> None:
        if status is RunStatus.RUNNING:
            raise ValueError("finish requires a terminal run status")
        connection.execute(
            etl_run.update()
            .where(etl_run.c.id == run_id)
            .values(
                status=status.value,
                finished_at=datetime.now(UTC),
                error_code=error_code,
            )
        )


class CheckpointRepository:
    def next_page(
        self,
        connection: Connection,
        scope_fingerprint: str,
        requested_page: int,
    ) -> int:
        checkpoint = (
            connection.execute(
                sa.select(
                    extraction_checkpoint.c.last_successful_page,
                    extraction_checkpoint.c.completed,
                ).where(extraction_checkpoint.c.scope_fingerprint == scope_fingerprint)
            )
            .mappings()
            .one_or_none()
        )
        if checkpoint is None or checkpoint["completed"]:
            return requested_page
        return checkpoint["last_successful_page"] + 1

    def advance(
        self,
        connection: Connection,
        scope_fingerprint: str,
        pipeline_name: str,
        dataset: RawDataset,
        mode: str,
        scope_params: dict[str, ParameterValue],
        last_successful_page: int,
        completed: bool,
    ) -> None:
        values = {
            "scope_fingerprint": scope_fingerprint,
            "pipeline_name": pipeline_name,
            "dataset": dataset.value,
            "mode": mode,
            "scope_params": scope_parameters(scope_params),
            "last_successful_page": last_successful_page,
            "completed": completed,
            "updated_at": datetime.now(UTC),
        }
        statement = postgresql.insert(extraction_checkpoint).values(values)
        excluded = statement.excluded
        advances_page = excluded.last_successful_page > extraction_checkpoint.c.last_successful_page
        completes_same_page = sa.and_(
            excluded.last_successful_page == extraction_checkpoint.c.last_successful_page,
            excluded.completed.is_(True),
            extraction_checkpoint.c.completed.is_(False),
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[extraction_checkpoint.c.scope_fingerprint],
                set_={key: value for key, value in values.items() if key != "scope_fingerprint"},
                where=sa.or_(advances_page, completes_same_page),
            )
        )
