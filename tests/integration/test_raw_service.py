import json
import os
from collections.abc import Mapping
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from govinsight.extract.pncp.errors import PNCPResponseError, PNCPRetryExhausted
from govinsight.extract.pncp.models import (
    ContractQuery,
    FetchedPNCPPage,
    PNCPPage,
    ProcurementQuery,
)
from govinsight.raw.hashing import scope_fingerprint
from govinsight.raw.models import RawDataset, RunStatus
from govinsight.raw.service import RawIngestionService
from govinsight.raw.tables import etl_run, etl_watermark, extraction_checkpoint, raw_api_response

type Query = ProcurementQuery | ContractQuery
type PageResult = PNCPPage | BaseException


class FakePNCPClient:
    def __init__(
        self,
        *,
        procurements: Mapping[int, PageResult] | None = None,
        contracts: Mapping[int, PageResult] | None = None,
        duration_ms: float = 8.125,
    ) -> None:
        self._procurements = procurements or {}
        self._contracts = contracts or {}
        self._duration_ms = duration_ms
        self.requests: list[tuple[RawDataset, int]] = []

    def fetch_procurements(self, query: ProcurementQuery) -> FetchedPNCPPage:
        endpoint = f"/v1/contratacoes/{query.mode.value}"
        return self._fetch(RawDataset.PROCUREMENTS, query, endpoint, self._procurements)

    def fetch_contracts(self, query: ContractQuery) -> FetchedPNCPPage:
        endpoint = "/v1/contratos"
        if query.mode.value == "atualizacao":
            endpoint += "/atualizacao"
        return self._fetch(RawDataset.CONTRACTS, query, endpoint, self._contracts)

    def _fetch(
        self,
        dataset: RawDataset,
        query: Query,
        endpoint: str,
        responses: Mapping[int, PageResult],
    ) -> FetchedPNCPPage:
        self.requests.append((dataset, query.page))
        response = responses.get(query.page)
        if response is None:
            raise AssertionError(f"unexpected {dataset.value} page {query.page}")
        if isinstance(response, BaseException):
            raise response

        raw_body = json.dumps(
            response.model_dump(by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return FetchedPNCPPage(
            page=response,
            raw_body=raw_body,
            endpoint=endpoint,
            request_params=query.to_params(),
            status_code=200,
            duration_ms=self._duration_ms,
            collected_at=datetime(2026, 8, 17, 18, 30, tzinfo=UTC),
        )


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for service integration tests")
    database_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield database_engine
    finally:
        database_engine.dispose()


def _page(
    records: list[dict[str, object]],
    *,
    number: int,
    total_pages: int,
    remaining_pages: int,
) -> PNCPPage:
    return PNCPPage(
        data=records,
        totalRegistros=3,
        totalPaginas=total_pages,
        numeroPagina=number,
        paginasRestantes=remaining_pages,
        empty=not records,
    )


def _procurement_query(identity: str) -> ProcurementQuery:
    return ProcurementQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 2),
        modality_code=6,
        page_size=10,
        administrative_unit_code=identity,
    )


def _contract_query(identity: str) -> ContractQuery:
    return ContractQuery(
        start_date=date(2025, 8, 3),
        end_date=date(2025, 8, 4),
        page_size=10,
        administrative_unit_code=identity,
    )


def _endpoint(dataset: RawDataset, query: Query) -> str:
    if dataset is RawDataset.PROCUREMENTS:
        return f"/v1/contratacoes/{query.mode.value}"
    suffix = "/atualizacao" if query.mode.value == "atualizacao" else ""
    return f"/v1/contratos{suffix}"


def _scope(dataset: RawDataset, query: Query) -> str:
    return scope_fingerprint("pncp", dataset.value, _endpoint(dataset, query), query.to_params())


def _cleanup(engine: Engine, *, pipeline_name: str, scope: str) -> None:
    with engine.begin() as connection:
        run_ids = sa.select(etl_run.c.id).where(etl_run.c.pipeline_name == pipeline_name)
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(
            extraction_checkpoint.delete().where(
                extraction_checkpoint.c.scope_fingerprint == scope,
                extraction_checkpoint.c.pipeline_name == pipeline_name,
            )
        )
        connection.execute(etl_run.delete().where(etl_run.c.pipeline_name == pipeline_name))


def _assert_watermark_empty(engine: Engine) -> None:
    with engine.connect() as connection:
        count = connection.execute(
            sa.select(sa.func.count()).select_from(etl_watermark)
        ).scalar_one()
    assert count == 0


@pytest.mark.integration
def test_two_page_ingestion_replay_is_idempotent_and_commits_final_checkpoint(
    engine: Engine,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-success-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)
    pages = {
        1: _page([{"id": "one"}, {"id": "two"}], number=1, total_pages=2, remaining_pages=1),
        2: _page([{"id": "three"}], number=2, total_pages=2, remaining_pages=0),
    }

    try:
        first_client = FakePNCPClient(procurements=pages)
        first = RawIngestionService(
            engine, first_client, pipeline_name=pipeline_name
        ).ingest_procurements(query)

        assert first.status is RunStatus.SUCCEEDED
        assert first.pages_processed == 2
        assert first.records_received == 3
        assert first.records_inserted == 3
        assert first.records_duplicate == 0

        second_client = FakePNCPClient(procurements=pages)
        second = RawIngestionService(
            engine, second_client, pipeline_name=pipeline_name
        ).ingest_procurements(query)

        assert second.status is RunStatus.SUCCEEDED
        assert second.pages_processed == 2
        assert second.records_received == 3
        assert second.records_inserted == 0
        assert second.records_duplicate == 3
        assert first_client.requests == [
            (RawDataset.PROCUREMENTS, 1),
            (RawDataset.PROCUREMENTS, 2),
        ]
        assert second_client.requests == first_client.requests

        with engine.connect() as connection:
            bronze_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()
            run_rows = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .all()
            )
            checkpoint = (
                connection.execute(
                    sa.select(extraction_checkpoint).where(
                        extraction_checkpoint.c.scope_fingerprint == scope
                    )
                )
                .mappings()
                .one()
            )

        assert bronze_count == 2
        assert len(run_rows) == 2
        replay_row = next(row for row in run_rows if row["id"] == second.run_id)
        assert replay_row["records_received"] == 3
        assert replay_row["records_inserted"] == 0
        assert replay_row["records_duplicate"] == 3
        assert checkpoint["last_successful_page"] == 2
        assert checkpoint["completed"] is True
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
def test_interrupted_run_is_failed_and_resumes_at_next_page(engine: Engine) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-resume-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)
    page_one = _page([{"id": "one"}, {"id": "two"}], number=1, total_pages=2, remaining_pages=1)
    page_two = _page([{"id": "three"}], number=2, total_pages=2, remaining_pages=0)
    interrupted_client = FakePNCPClient(
        procurements={
            1: page_one,
            2: PNCPRetryExhausted(endpoint="/v1/contratacoes/publicacao", attempts=3),
        }
    )

    try:
        with pytest.raises(PNCPRetryExhausted):
            RawIngestionService(
                engine, interrupted_client, pipeline_name=pipeline_name
            ).ingest_procurements(query)

        with engine.connect() as connection:
            first_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )
            first_bronze_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()
            incomplete = (
                connection.execute(
                    sa.select(extraction_checkpoint).where(
                        extraction_checkpoint.c.scope_fingerprint == scope
                    )
                )
                .mappings()
                .one()
            )

        assert first_run["status"] == RunStatus.FAILED.value
        assert first_run["error_code"] == "PNCP_ERROR"
        assert first_run["pages_processed"] == 1
        assert first_bronze_count == 1
        assert incomplete["last_successful_page"] == 1
        assert incomplete["completed"] is False

        resume_client = FakePNCPClient(procurements={2: page_two})
        resumed = RawIngestionService(
            engine, resume_client, pipeline_name=pipeline_name
        ).ingest_procurements(query)

        assert resumed.status is RunStatus.SUCCEEDED
        assert resumed.pages_processed == 1
        assert resumed.records_received == 1
        assert resumed.records_inserted == 1
        assert resumed.records_duplicate == 0
        assert resume_client.requests == [(RawDataset.PROCUREMENTS, 2)]

        with engine.connect() as connection:
            completed = (
                connection.execute(
                    sa.select(extraction_checkpoint).where(
                        extraction_checkpoint.c.scope_fingerprint == scope
                    )
                )
                .mappings()
                .one()
            )
            final_bronze_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()

        assert completed["last_successful_page"] == 2
        assert completed["completed"] is True
        assert final_bronze_count == 2
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
def test_mismatched_response_page_fails_before_raw_or_checkpoint_persistence(
    engine: Engine,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-page-mismatch-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)
    client = FakePNCPClient(
        procurements={1: _page([{"id": "wrong-page"}], number=2, total_pages=2, remaining_pages=0)}
    )

    try:
        with pytest.raises(PNCPResponseError) as caught:
            RawIngestionService(engine, client, pipeline_name=pipeline_name).ingest_procurements(
                query
            )

        assert "expected page 1" in caught.value.reason
        assert "received page 2" in caught.value.reason
        assert client.requests == [(RawDataset.PROCUREMENTS, 1)]

        with engine.connect() as connection:
            failed_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )
            raw_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()
            checkpoint_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(extraction_checkpoint)
                .where(extraction_checkpoint.c.scope_fingerprint == scope)
            ).scalar_one()

        assert failed_run["status"] == RunStatus.FAILED.value
        assert failed_run["error_code"] == "PNCP_ERROR"
        assert failed_run["pages_processed"] == 0
        assert raw_count == 0
        assert checkpoint_count == 0
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
@pytest.mark.parametrize("mismatch", ["endpoint", "params"])
def test_mismatched_response_identity_fails_before_raw_or_checkpoint_persistence(
    engine: Engine,
    mismatch: str,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-identity-mismatch-{mismatch}-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)

    class MismatchedMetadataClient(FakePNCPClient):
        def fetch_procurements(self, requested: ProcurementQuery) -> FetchedPNCPPage:
            fetched = super().fetch_procurements(requested)
            if mismatch == "endpoint":
                return fetched.model_copy(update={"endpoint": "/v1/contratos"})
            wrong_params = dict(fetched.request_params)
            wrong_params["tamanhoPagina"] = 50
            return fetched.model_copy(update={"request_params": wrong_params})

    client = MismatchedMetadataClient(
        procurements={
            1: _page([{"id": "wrong-identity"}], number=1, total_pages=1, remaining_pages=0)
        }
    )

    try:
        with pytest.raises(PNCPResponseError) as caught:
            RawIngestionService(engine, client, pipeline_name=pipeline_name).ingest_procurements(
                query
            )

        assert caught.value.endpoint == "/v1/contratacoes/publicacao"
        assert caught.value.reason == f"unexpected response {mismatch}"
        assert client.requests == [(RawDataset.PROCUREMENTS, 1)]

        with engine.connect() as connection:
            failed_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )
            raw_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()
            checkpoint_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(extraction_checkpoint)
                .where(extraction_checkpoint.c.scope_fingerprint == scope)
            ).scalar_one()

        assert failed_run["status"] == RunStatus.FAILED.value
        assert failed_run["error_code"] == "PNCP_ERROR"
        assert failed_run["pages_processed"] == 0
        assert raw_count == 0
        assert checkpoint_count == 0
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
def test_contract_ingestion_routes_to_contract_fetch_and_persists_contract_dataset(
    engine: Engine,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-contract-{identity}"
    query = _contract_query(identity)
    scope = _scope(RawDataset.CONTRACTS, query)
    client = FakePNCPClient(
        contracts={1: _page([{"id": "contract"}], number=1, total_pages=1, remaining_pages=0)}
    )

    try:
        result = RawIngestionService(engine, client, pipeline_name=pipeline_name).ingest_contracts(
            query
        )

        assert result.status is RunStatus.SUCCEEDED
        assert client.requests == [(RawDataset.CONTRACTS, 1)]
        with engine.connect() as connection:
            stored = (
                connection.execute(
                    sa.select(raw_api_response.c.dataset, raw_api_response.c.endpoint)
                    .select_from(raw_api_response.join(etl_run))
                    .where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )
        assert stored == {"dataset": "contracts", "endpoint": "/v1/contratos"}
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
def test_checkpoint_read_failure_preserves_run_and_classifies_persistence_error(
    engine: Engine,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-checkpoint-error-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)
    client = FakePNCPClient(
        procurements={1: _page([{"id": "unused"}], number=1, total_pages=1, remaining_pages=0)}
    )
    timeout_engine = create_engine(
        engine.url,
        connect_args={"options": "-c lock_timeout=100ms"},
        pool_pre_ping=True,
    )

    lock_connection = engine.connect()
    lock_transaction = lock_connection.begin()
    lock_connection.exec_driver_sql(
        "LOCK TABLE control.extraction_checkpoint IN ACCESS EXCLUSIVE MODE"
    )
    try:
        with pytest.raises(sa.exc.OperationalError):
            RawIngestionService(
                timeout_engine, client, pipeline_name=pipeline_name
            ).ingest_procurements(query)

        with engine.connect() as connection:
            failed_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )

        assert failed_run["status"] == RunStatus.FAILED.value
        assert failed_run["error_code"] == "PERSISTENCE_ERROR"
        assert failed_run["pages_processed"] == 0
        assert client.requests == []
        _assert_watermark_empty(engine)
    finally:
        lock_transaction.rollback()
        lock_connection.close()
        timeout_engine.dispose()
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
def test_failure_finalization_propagates_persistence_error_and_leaves_run_unreconciled(
    engine: Engine,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-finalization-error-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)
    timeout_engine = create_engine(
        engine.url,
        connect_args={"options": "-c lock_timeout=100ms"},
        pool_pre_ping=True,
    )
    lock_connection: sa.Connection | None = None
    lock_transaction: sa.Transaction | None = None

    class LockingFailureClient:
        def fetch_procurements(self, _query: ProcurementQuery) -> FetchedPNCPPage:
            nonlocal lock_connection, lock_transaction
            lock_connection = engine.connect()
            lock_transaction = lock_connection.begin()
            locked_run = lock_connection.execute(
                sa.select(etl_run.c.id)
                .where(etl_run.c.pipeline_name == pipeline_name)
                .with_for_update()
            ).scalar_one()
            assert locked_run is not None
            raise PNCPRetryExhausted(endpoint="/v1/contratacoes/publicacao", attempts=3)

        def fetch_contracts(self, _query: ContractQuery) -> FetchedPNCPPage:
            raise AssertionError("contract fetch is not expected")

    try:
        with pytest.raises(sa.exc.OperationalError):
            RawIngestionService(
                timeout_engine,
                LockingFailureClient(),
                pipeline_name=pipeline_name,
            ).ingest_procurements(query)

        with engine.connect() as connection:
            unfinished_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )

        assert unfinished_run["status"] == RunStatus.RUNNING.value
        assert unfinished_run["finished_at"] is None
        assert unfinished_run["error_code"] is None
        _assert_watermark_empty(engine)
    finally:
        if lock_transaction is not None:
            lock_transaction.rollback()
        if lock_connection is not None:
            lock_connection.close()
        timeout_engine.dispose()
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("client", "expected_exception", "error_code"),
    [
        (
            FakePNCPClient(
                procurements={
                    1: _page(
                        [{"secret": "do-not-store"}], number=1, total_pages=1, remaining_pages=0
                    )
                },
                duration_ms=1_000_000_000_000,
            ),
            sa.exc.SQLAlchemyError,
            "PERSISTENCE_ERROR",
        ),
        (
            FakePNCPClient(procurements={1: RuntimeError("secret response body")}),
            RuntimeError,
            "INGESTION_ERROR",
        ),
    ],
)
def test_failures_store_only_safe_error_codes_and_leave_no_partial_page(
    engine: Engine,
    client: FakePNCPClient,
    expected_exception: type[BaseException],
    error_code: str,
) -> None:
    identity = uuid4().hex
    pipeline_name = f"service-errors-{identity}"
    query = _procurement_query(identity)
    scope = _scope(RawDataset.PROCUREMENTS, query)

    try:
        with pytest.raises(expected_exception):
            RawIngestionService(engine, client, pipeline_name=pipeline_name).ingest_procurements(
                query
            )

        with engine.connect() as connection:
            failed_run = (
                connection.execute(
                    sa.select(etl_run).where(etl_run.c.pipeline_name == pipeline_name)
                )
                .mappings()
                .one()
            )
            raw_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(raw_api_response.join(etl_run))
                .where(etl_run.c.pipeline_name == pipeline_name)
            ).scalar_one()
            checkpoint_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(extraction_checkpoint)
                .where(extraction_checkpoint.c.scope_fingerprint == scope)
            ).scalar_one()

        assert failed_run["status"] == RunStatus.FAILED.value
        assert failed_run["error_code"] == error_code
        assert "secret" not in failed_run["error_code"].lower()
        assert raw_count == 0
        assert checkpoint_count == 0
        _assert_watermark_empty(engine)
    finally:
        _cleanup(engine, pipeline_name=pipeline_name, scope=scope)
