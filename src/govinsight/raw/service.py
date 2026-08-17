from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Engine

from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.errors import PNCPError
from govinsight.extract.pncp.models import (
    ContractQuery,
    FetchedPNCPPage,
    ProcurementQuery,
    QueryMode,
)

from .hashing import request_fingerprint, scope_fingerprint, sha256_text
from .models import IngestionResult, RawCapture, RawDataset, RunStatus
from .repositories import CheckpointRepository, RawResponseRepository, RunRepository

Query = TypeVar("Query", ProcurementQuery, ContractQuery)


class RawIngestionService:
    def __init__(
        self,
        engine: Engine,
        client: PNCPClient,
        pipeline_name: str = "pncp_raw",
    ) -> None:
        self._engine = engine
        self._client = client
        self._pipeline_name = pipeline_name
        self._raw_responses = RawResponseRepository()
        self._runs = RunRepository()
        self._checkpoints = CheckpointRepository()

    def ingest_procurements(self, query: ProcurementQuery) -> IngestionResult:
        return self._ingest(
            RawDataset.PROCUREMENTS,
            query,
            self._client.fetch_procurements,
        )

    def ingest_contracts(self, query: ContractQuery) -> IngestionResult:
        return self._ingest(
            RawDataset.CONTRACTS,
            query,
            self._client.fetch_contracts,
        )

    def _ingest(
        self,
        dataset: RawDataset,
        query: Query,
        fetch_page: Callable[[Query], FetchedPNCPPage],
    ) -> IngestionResult:
        endpoint = self._endpoint(dataset, query.mode)
        initial_params = query.to_params()
        initial_request_fingerprint = request_fingerprint(
            "pncp", dataset.value, endpoint, initial_params
        )
        checkpoint_fingerprint = scope_fingerprint("pncp", dataset.value, endpoint, initial_params)

        with self._engine.begin() as connection:
            run_id = self._runs.create(
                connection,
                pipeline_name=self._pipeline_name,
                dataset=dataset,
                mode=query.mode.value,
            )

        pages_processed = 0
        records_received = 0
        records_inserted = 0
        records_duplicate = 0

        try:
            with self._engine.begin() as connection:
                page_number = self._checkpoints.next_page(
                    connection,
                    scope_fingerprint=checkpoint_fingerprint,
                    requested_page=query.page,
                )

            while True:
                page_query = query.model_copy(update={"page": page_number})
                fetched = fetch_page(page_query)
                requested_params = page_query.to_params()
                requested_fingerprint = (
                    initial_request_fingerprint
                    if requested_params == initial_params
                    else request_fingerprint("pncp", dataset.value, endpoint, requested_params)
                )
                actual_fingerprint = request_fingerprint(
                    "pncp",
                    dataset.value,
                    fetched.endpoint,
                    fetched.request_params,
                )
                capture = RawCapture(
                    etl_run_id=run_id,
                    source="pncp",
                    dataset=dataset,
                    endpoint=fetched.endpoint,
                    request_params=fetched.request_params,
                    request_fingerprint=(
                        requested_fingerprint
                        if fetched.endpoint == endpoint
                        and fetched.request_params == requested_params
                        else actual_fingerprint
                    ),
                    window_start=query.start_date,
                    window_end=query.end_date,
                    page_number=fetched.page.page_number,
                    http_status=fetched.status_code,
                    raw_body=fetched.raw_body,
                    body_sha256=sha256_text(fetched.raw_body),
                    record_count=len(fetched.page.data),
                    collected_at=fetched.collected_at,
                    duration_ms=fetched.duration_ms,
                )
                is_final = self._is_final(fetched)

                with self._engine.begin() as connection:
                    outcome = self._raw_responses.insert(connection, capture)
                    self._runs.apply_page(
                        connection,
                        run_id,
                        record_count=capture.record_count,
                        inserted=outcome.inserted,
                    )
                    self._checkpoints.advance(
                        connection,
                        scope_fingerprint=checkpoint_fingerprint,
                        pipeline_name=self._pipeline_name,
                        dataset=dataset,
                        mode=query.mode.value,
                        scope_params=requested_params,
                        last_successful_page=fetched.page.page_number,
                        completed=is_final,
                    )

                pages_processed += 1
                records_received += capture.record_count
                if outcome.inserted:
                    records_inserted += capture.record_count
                else:
                    records_duplicate += capture.record_count

                if is_final:
                    break
                page_number = fetched.page.page_number + 1

            with self._engine.begin() as connection:
                self._runs.finish(connection, run_id, RunStatus.SUCCEEDED)
        except PNCPError:
            self._try_mark_failed(run_id, "PNCP_ERROR")
            raise
        except sa.exc.SQLAlchemyError:
            self._try_mark_failed(run_id, "PERSISTENCE_ERROR")
            raise
        except Exception:
            self._try_mark_failed(run_id, "INGESTION_ERROR")
            raise

        return IngestionResult(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            pages_processed=pages_processed,
            records_received=records_received,
            records_inserted=records_inserted,
            records_duplicate=records_duplicate,
        )

    def _try_mark_failed(self, run_id: UUID, error_code: str) -> None:
        try:
            with self._engine.begin() as connection:
                self._runs.finish(connection, run_id, RunStatus.FAILED, error_code=error_code)
        except Exception:
            pass

    @staticmethod
    def _endpoint(dataset: RawDataset, mode: QueryMode) -> str:
        if dataset is RawDataset.PROCUREMENTS:
            return f"/v1/contratacoes/{mode.value}"
        if mode is QueryMode.UPDATE:
            return "/v1/contratos/atualizacao"
        return "/v1/contratos"

    @staticmethod
    def _is_final(fetched: FetchedPNCPPage) -> bool:
        page = fetched.page
        return (
            page.empty
            or page.remaining_pages == 0
            or (page.total_pages > 0 and page.page_number >= page.total_pages)
        )
