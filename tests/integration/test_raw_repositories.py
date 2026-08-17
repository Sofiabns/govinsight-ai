import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from govinsight.raw.hashing import (
    request_fingerprint,
    scope_fingerprint,
    sha256_text,
)
from govinsight.raw.models import InsertOutcome, RawCapture, RawDataset, RunStatus
from govinsight.raw.repositories import (
    CheckpointRepository,
    RawResponseRepository,
    RunRepository,
)
from govinsight.raw.tables import etl_run, extraction_checkpoint, raw_api_response

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"
)


class ForcedRollback(Exception):
    pass


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for repository integration tests")
    database_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


def _capture(run_id: UUID, *, identity: str, raw_body: str | None = None) -> RawCapture:
    body = FIXTURE_PATH.read_text(encoding="utf-8") if raw_body is None else raw_body
    request_params = {
        "dataFinal": "20250831",
        "dataInicial": "20250801",
        "pagina": 1,
        "tamanhoPagina": 50,
    }
    endpoint = f"/v1/contratacoes/publicacao/{identity}"
    return RawCapture(
        etl_run_id=run_id,
        source="pncp",
        dataset=RawDataset.PROCUREMENTS,
        endpoint=endpoint,
        request_params=request_params,
        request_fingerprint=request_fingerprint(
            "pncp", RawDataset.PROCUREMENTS.value, endpoint, request_params
        ),
        window_start=date(2025, 8, 1),
        window_end=date(2025, 8, 31),
        page_number=1,
        http_status=200,
        raw_body=body,
        body_sha256=sha256_text(body),
        record_count=len(json.loads(body)["data"]),
        collected_at=datetime(2025, 8, 17, 12, tzinfo=UTC),
        duration_ms=12.375,
    )


def _create_run(connection: sa.Connection, *, pipeline_name: str) -> UUID:
    return RunRepository().create(
        connection,
        pipeline_name=pipeline_name,
        dataset=RawDataset.PROCUREMENTS,
        mode="publicacao",
    )


def _delete_runs(engine: Engine, run_ids: list[UUID]) -> None:
    with engine.begin() as connection:
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(run_ids)))


@pytest.mark.integration
def test_raw_insert_is_idempotent_across_runs_and_preserves_exact_utf8(engine: Engine) -> None:
    raw_repository = RawResponseRepository()
    identity = uuid4().hex

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            first_run = _create_run(connection, pipeline_name=f"repo-idempotent-{identity}-1")
            second_run = _create_run(connection, pipeline_name=f"repo-idempotent-{identity}-2")
            capture = _capture(first_run, identity=identity)

            first = raw_repository.insert(connection, capture)
            second = raw_repository.insert(
                connection, capture.model_copy(update={"etl_run_id": second_run})
            )

            assert first.inserted is True
            assert first.raw_response_id is not None
            assert second == InsertOutcome(inserted=False, raw_response_id=None)

            stored_body = connection.execute(
                sa.select(raw_api_response.c.raw_body).where(
                    raw_api_response.c.id == first.raw_response_id
                )
            ).scalar_one()
            fixture_body = FIXTURE_PATH.read_text(encoding="utf-8")
            assert stored_body.encode("utf-8") == fixture_body.encode("utf-8")
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_raw_insert_versions_a_changed_body_and_hash(engine: Engine) -> None:
    raw_repository = RawResponseRepository()
    identity = uuid4().hex

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            run_id = _create_run(connection, pipeline_name=f"repo-version-{identity}")
            capture = _capture(run_id, identity=identity)
            changed_body = capture.raw_body + "\n"
            changed_capture = capture.model_copy(
                update={"raw_body": changed_body, "body_sha256": sha256_text(changed_body)}
            )

            first = raw_repository.insert(connection, capture)
            second = raw_repository.insert(connection, changed_capture)

            assert first.inserted is True
            assert second.inserted is True
            assert second.raw_response_id != first.raw_response_id
            assert (
                connection.execute(
                    sa.select(sa.func.count())
                    .select_from(raw_api_response)
                    .where(raw_api_response.c.request_fingerprint == capture.request_fingerprint)
                ).scalar_one()
                == 2
            )
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_run_repository_tracks_inserted_and_duplicate_records_and_finishes(engine: Engine) -> None:
    raw_repository = RawResponseRepository()
    run_repository = RunRepository()
    identity = uuid4().hex

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            run_id = _create_run(connection, pipeline_name=f"repo-counters-{identity}")
            capture = _capture(run_id, identity=identity)
            inserted = raw_repository.insert(connection, capture)
            duplicate = raw_repository.insert(connection, capture)

            run_repository.apply_page(
                connection,
                run_id,
                record_count=capture.record_count,
                inserted=inserted.inserted,
            )
            run_repository.apply_page(
                connection,
                run_id,
                record_count=capture.record_count,
                inserted=duplicate.inserted,
            )
            run_repository.finish(connection, run_id, RunStatus.SUCCEEDED)

            row = (
                connection.execute(sa.select(etl_run).where(etl_run.c.id == run_id))
                .mappings()
                .one()
            )
            assert row["status"] == "SUCCEEDED"
            assert row["finished_at"] is not None
            assert row["error_code"] is None
            assert row["pages_processed"] == 2
            assert row["records_received"] == capture.record_count * 2
            assert row["records_inserted"] == capture.record_count
            assert row["records_duplicate"] == capture.record_count
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_checkpoint_resumes_incomplete_scope_but_restarts_completed_scope(engine: Engine) -> None:
    repository = CheckpointRepository()
    identity = uuid4().hex
    params = {"pagina": 3, "tamanhoPagina": 50, "dataInicial": "20250801"}
    fingerprint = scope_fingerprint(
        "pncp", RawDataset.PROCUREMENTS.value, f"/checkpoint/{identity}", params
    )

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert repository.next_page(connection, fingerprint, requested_page=1) == 1

            repository.advance(
                connection,
                scope_fingerprint=fingerprint,
                pipeline_name=f"repo-checkpoint-{identity}",
                dataset=RawDataset.PROCUREMENTS,
                mode="publicacao",
                scope_params=params,
                last_successful_page=3,
                completed=False,
            )
            assert repository.next_page(connection, fingerprint, requested_page=1) == 4

            stored_scope = connection.execute(
                sa.select(extraction_checkpoint.c.scope_params).where(
                    extraction_checkpoint.c.scope_fingerprint == fingerprint
                )
            ).scalar_one()
            assert stored_scope == {"tamanhoPagina": 50, "dataInicial": "20250801"}

            repository.advance(
                connection,
                scope_fingerprint=fingerprint,
                pipeline_name=f"repo-checkpoint-{identity}",
                dataset=RawDataset.PROCUREMENTS,
                mode="publicacao",
                scope_params=params,
                last_successful_page=3,
                completed=True,
            )
            assert repository.next_page(connection, fingerprint, requested_page=7) == 7
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_concurrent_duplicate_raw_inserts_create_exactly_one_row(engine: Engine) -> None:
    identity = uuid4().hex
    pipeline_prefix = f"repo-concurrent-{identity}"
    with engine.begin() as connection:
        run_ids = [
            _create_run(connection, pipeline_name=f"{pipeline_prefix}-{suffix}")
            for suffix in (1, 2)
        ]

    barrier = Barrier(2)

    def insert_for_run(run_id: UUID) -> bool:
        capture = _capture(run_id, identity=identity)
        with engine.begin() as connection:
            barrier.wait(timeout=5)
            return RawResponseRepository().insert(connection, capture).inserted

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            inserted_results = list(executor.map(insert_for_run, run_ids))

        with engine.connect() as connection:
            matching_rows = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response)
                .where(
                    raw_api_response.c.request_fingerprint
                    == _capture(run_ids[0], identity=identity).request_fingerprint
                )
            ).scalar_one()

        assert sorted(inserted_results) == [False, True]
        assert matching_rows == 1
    finally:
        _delete_runs(engine, run_ids)


@pytest.mark.integration
def test_page_transaction_rolls_back_raw_counters_and_checkpoint_together(engine: Engine) -> None:
    identity = uuid4().hex
    pipeline_name = f"repo-rollback-{identity}"
    with engine.begin() as connection:
        run_id = _create_run(connection, pipeline_name=pipeline_name)

    capture = _capture(run_id, identity=identity)
    params = dict(capture.request_params)
    fingerprint = scope_fingerprint(capture.source, capture.dataset.value, capture.endpoint, params)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                outcome = RawResponseRepository().insert(connection, capture)
                RunRepository().apply_page(
                    connection,
                    run_id,
                    record_count=capture.record_count,
                    inserted=outcome.inserted,
                )
                CheckpointRepository().advance(
                    connection,
                    scope_fingerprint=fingerprint,
                    pipeline_name=pipeline_name,
                    dataset=capture.dataset,
                    mode="publicacao",
                    scope_params=params,
                    last_successful_page=1,
                    completed=False,
                )
                raise ForcedRollback
            except ForcedRollback:
                transaction.rollback()

        with engine.connect() as connection:
            raw_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response)
                .where(raw_api_response.c.request_fingerprint == capture.request_fingerprint)
            ).scalar_one()
            run_row = connection.execute(
                sa.select(
                    etl_run.c.pages_processed,
                    etl_run.c.records_received,
                    etl_run.c.records_inserted,
                    etl_run.c.records_duplicate,
                ).where(etl_run.c.id == run_id)
            ).one()
            checkpoint_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(extraction_checkpoint)
                .where(extraction_checkpoint.c.scope_fingerprint == fingerprint)
            ).scalar_one()

        assert raw_count == 0
        assert run_row == (0, 0, 0, 0)
        assert checkpoint_count == 0
    finally:
        _delete_runs(engine, [run_id])
