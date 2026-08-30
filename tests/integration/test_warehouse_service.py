import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from structlog.testing import capture_logs

from govinsight.quality.repositories import QualityWatermarkRepository
from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.raw.tables import etl_run, etl_watermark, raw_api_response
from govinsight.transform.procurement import parse_procurement
from govinsight.transform.repositories import ProcurementRepository, SilverWatermarkRepository
from govinsight.transform.tables import procurement, rejected_record
from govinsight.warehouse.models import (
    ReconciliationResult,
    WarehouseLoadResult,
    WarehouseLoadStatus,
    WarehouseStateError,
)
from govinsight.warehouse.repositories import WarehouseRepository, WarehouseWatermarkRepository
from govinsight.warehouse.service import WarehouseLoadService
from govinsight.warehouse.tables import (
    dim_date,
    dim_modality,
    dim_organization,
    dim_unit,
    fact_procurement,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"
WATERMARK_KEYS = (
    ("silver_procurement", "silver"),
    ("data_quality", "quality"),
    ("gold_procurement", "gold"),
)


@dataclass
class WarehouseTestScope:
    identity: str = field(default_factory=lambda: uuid4().hex)
    pncp_keys: set[str] = field(default_factory=set)
    cnpjs: set[str] = field(default_factory=set)
    modality_ids: set[int] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    raw_ids: list[int] = field(default_factory=list)
    run_ids: list[UUID] = field(default_factory=list)
    saved_watermarks: list[dict[str, object]] = field(default_factory=list)


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for warehouse integration tests")
    value = create_engine(database_url, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


def _records(scope: WarehouseTestScope) -> list[dict[str, object]]:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    number = int(scope.identity[:12], 16)
    first_cnpj = f"{number % 10**14:014d}"
    second_cnpj = f"{(number + 1) % 10**14:014d}"
    modality_id = 1000 + number % 100000
    first = deepcopy(base)
    first["numeroControlePNCP"] = f"{first_cnpj}-1-000001/2025"
    first["orgaoEntidade"]["cnpj"] = first_cnpj
    first["unidadeOrgao"]["codigoUnidade"] = f"U-{scope.identity[:8]}-1"
    first["modalidadeId"] = modality_id
    first["valorTotalEstimado"] = 100.25
    first["valorTotalHomologado"] = 300

    second = deepcopy(base)
    second["numeroControlePNCP"] = f"{second_cnpj}-1-000002/2025"
    second["orgaoEntidade"] = {
        "cnpj": second_cnpj,
        "razaoSocial": "Órgão Dois",
        "poderId": "E",
        "esferaId": "M",
    }
    second["unidadeOrgao"] = {
        "codigoUnidade": f"U-{scope.identity[:8]}-2",
        "nomeUnidade": "Unidade Dois",
        "codigoIbge": "3550308",
        "municipioNome": "São Paulo",
        "ufSigla": "SP",
        "ufNome": "São Paulo",
    }
    second["sequencialCompra"] = 2
    second["modalidadeId"] = modality_id
    second["dataPublicacaoPncp"] = "2025-08-02T10:00:00"
    second["dataAberturaProposta"] = "2025-08-03T10:00:00"
    second["dataEncerramentoProposta"] = "2025-08-04T10:00:00"
    second["dataAtualizacaoGlobal"] = "2025-08-02T11:00:00"
    second["valorTotalEstimado"] = 250
    second["valorTotalHomologado"] = None
    scope.pncp_keys.update({str(first["numeroControlePNCP"]), str(second["numeroControlePNCP"])})
    scope.cnpjs.update({first_cnpj, second_cnpj})
    scope.modality_ids.add(modality_id)
    scope.dates.update(
        {
            date(2025, 8, 1),
            date(2025, 8, 2),
            date(2025, 8, 3),
            date(2025, 8, 4),
            date(2025, 9, 1),
        }
    )
    return [first, second]


def _insert_raw(
    engine: Engine,
    records: list[dict[str, object]],
    scope: WarehouseTestScope,
) -> int:
    identity = uuid4().hex
    body = json.dumps({"data": records}, ensure_ascii=False, separators=(",", ":"))
    params = {"pagina": 1, "tamanhoPagina": 10}
    endpoint = f"/warehouse-test/{identity}"
    with engine.begin() as connection:
        run_id = RunRepository().create(
            connection,
            pipeline_name=f"warehouse-test-{identity}",
            dataset=RawDataset.PROCUREMENTS,
            mode="publicacao",
        )
        scope.run_ids.append(run_id)
        outcome = RawResponseRepository().insert(
            connection,
            RawCapture(
                etl_run_id=run_id,
                source="pncp",
                dataset=RawDataset.PROCUREMENTS,
                endpoint=endpoint,
                request_params=params,
                request_fingerprint=request_fingerprint(
                    "pncp", RawDataset.PROCUREMENTS.value, endpoint, params
                ),
                window_start=date(2025, 8, 1),
                window_end=date(2025, 8, 2),
                page_number=1,
                http_status=200,
                raw_body=body,
                body_sha256=sha256_text(body),
                record_count=len(records),
                collected_at=datetime.now(UTC),
                duration_ms=1,
            ),
        )
    assert outcome.raw_response_id is not None
    scope.raw_ids.append(outcome.raw_response_id)
    return outcome.raw_response_id


def _seed_silver(
    engine: Engine,
    records: list[dict[str, object]],
    scope: WarehouseTestScope,
) -> int:
    raw_id = _insert_raw(engine, records, scope)
    with engine.begin() as connection:
        for index, record in enumerate(records):
            parsed = parse_procurement(record, raw_response_id=raw_id, record_index=index)
            assert parsed.procurement is not None
            ProcurementRepository().upsert(connection, parsed.procurement)
        SilverWatermarkRepository().advance(connection, raw_id)
    return raw_id


def _watermark_condition() -> sa.ColumnElement[bool]:
    return sa.or_(
        *(
            sa.and_(
                etl_watermark.c.pipeline_name == pipeline,
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == stage,
            )
            for pipeline, stage in WATERMARK_KEYS
        )
    )


def _start_scope(engine: Engine) -> WarehouseTestScope:
    scope = WarehouseTestScope()
    with engine.begin() as connection:
        scope.saved_watermarks = [
            dict(row)
            for row in connection.execute(
                sa.select(etl_watermark).where(_watermark_condition())
            ).mappings()
        ]
        connection.execute(etl_watermark.delete().where(_watermark_condition()))
    return scope


def _cleanup(engine: Engine, scope: WarehouseTestScope) -> None:
    with engine.begin() as connection:
        connection.execute(
            fact_procurement.delete().where(
                fact_procurement.c.numero_controle_pncp.in_(scope.pncp_keys)
            )
        )
        date_is_referenced = sa.exists(
            sa.select(1).where(
                sa.or_(
                    fact_procurement.c.publication_date_key == dim_date.c.date_key,
                    fact_procurement.c.opening_date_key == dim_date.c.date_key,
                    fact_procurement.c.closing_date_key == dim_date.c.date_key,
                )
            )
        )
        connection.execute(
            dim_date.delete().where(
                dim_date.c.full_date.in_(scope.dates),
                sa.not_(date_is_referenced),
            )
        )
        connection.execute(
            dim_modality.delete().where(dim_modality.c.modalidade_id.in_(scope.modality_ids))
        )
        connection.execute(dim_unit.delete().where(dim_unit.c.orgao_cnpj.in_(scope.cnpjs)))
        connection.execute(
            dim_organization.delete().where(dim_organization.c.orgao_cnpj.in_(scope.cnpjs))
        )
        connection.execute(
            rejected_record.delete().where(
                rejected_record.c.source_raw_response_id.in_(scope.raw_ids)
            )
        )
        connection.execute(
            procurement.delete().where(procurement.c.numero_controle_pncp.in_(scope.pncp_keys))
        )
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.id.in_(scope.raw_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(scope.run_ids)))
        connection.execute(etl_watermark.delete().where(_watermark_condition()))
        if scope.saved_watermarks:
            connection.execute(etl_watermark.insert(), scope.saved_watermarks)


def _approve_quality(engine: Engine, raw_id: int) -> None:
    with engine.begin() as connection:
        QualityWatermarkRepository().advance(connection, raw_id)


def _gold_counts(engine: Engine, scope: WarehouseTestScope) -> tuple[int, int, int, int, int]:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.select(sa.func.count()).where(dim_date.c.full_date.in_(scope.dates))
            ).scalar_one(),
            connection.execute(
                sa.select(sa.func.count()).where(dim_organization.c.orgao_cnpj.in_(scope.cnpjs))
            ).scalar_one(),
            connection.execute(
                sa.select(sa.func.count()).where(dim_unit.c.orgao_cnpj.in_(scope.cnpjs))
            ).scalar_one(),
            connection.execute(
                sa.select(sa.func.count()).where(
                    dim_modality.c.modalidade_id.in_(scope.modality_ids)
                )
            ).scalar_one(),
            connection.execute(
                sa.select(sa.func.count()).where(
                    fact_procurement.c.numero_controle_pncp.in_(scope.pncp_keys)
                )
            ).scalar_one(),
        )


def _gold_watermark(engine: Engine) -> int:
    with engine.connect() as connection:
        return WarehouseWatermarkRepository().read_state(connection).gold


def _wait_for_advisory_waiters(engine: Engine, expected: int) -> None:
    deadline = time.monotonic() + 5
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            waiters = connection.execute(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND lower(wait_event) = 'advisory'"
                )
            ).scalar_one()
            if waiters >= expected:
                return
            time.sleep(0.01)
    raise AssertionError(f"expected {expected} advisory lock waiters")


@pytest.mark.integration
def test_repository_builds_reconciled_star(engine: Engine) -> None:
    """Catch broken grains, dimension joins, lineage, date roles, or money reconciliation."""
    scope = _start_scope(engine)
    records = _records(scope)
    repository = WarehouseRepository()

    try:
        _seed_silver(engine, records, scope)
        with engine.begin() as connection:
            counts = repository.load_dimensions(connection)
            counts["facts"] = repository.load_facts(connection)
            reconciliation = repository.reconcile(connection)

        assert counts == {
            "dates": 5,
            "organizations": 2,
            "units": 2,
            "modalities": 1,
            "facts": 2,
        }
        assert reconciliation == ReconciliationResult(
            silver_rows=2,
            fact_rows=2,
            missing_in_fact=0,
            missing_in_silver=0,
            orphan_foreign_keys=0,
            lineage_mismatches=0,
            estimated_silver=Decimal("350.2500"),
            estimated_fact=Decimal("350.2500"),
            estimated_nulls_silver=0,
            estimated_nulls_fact=0,
            homologated_silver=Decimal("300.0000"),
            homologated_fact=Decimal("300.0000"),
            homologated_nulls_silver=1,
            homologated_nulls_fact=1,
        )
        assert reconciliation.is_valid is True

        with engine.connect() as connection:
            publication = dim_date.alias("publication_test")
            opening = dim_date.alias("opening_test")
            closing = dim_date.alias("closing_test")
            joined = connection.execute(
                sa.select(
                    fact_procurement.c.numero_controle_pncp,
                    dim_organization.c.orgao_cnpj,
                    dim_unit.c.codigo_unidade,
                    dim_modality.c.modalidade_id,
                    publication.c.full_date.label("publication_date"),
                    opening.c.full_date.label("opening_date"),
                    closing.c.full_date.label("closing_date"),
                )
                .join(dim_organization)
                .join(dim_unit)
                .join(dim_modality)
                .join(
                    publication,
                    fact_procurement.c.publication_date_key == publication.c.date_key,
                )
                .outerjoin(opening, fact_procurement.c.opening_date_key == opening.c.date_key)
                .outerjoin(closing, fact_procurement.c.closing_date_key == closing.c.date_key)
                .where(fact_procurement.c.numero_controle_pncp.in_(scope.pncp_keys))
                .order_by(fact_procurement.c.numero_controle_pncp)
            ).all()
        assert len(joined) == 2
        roles = {
            row.numero_controle_pncp: (
                row.publication_date,
                row.opening_date,
                row.closing_date,
            )
            for row in joined
        }
        assert roles[str(records[0]["numeroControlePNCP"])] == (
            date(2025, 8, 1),
            date(2025, 8, 1),
            date(2025, 9, 1),
        )
        assert roles[str(records[1]["numeroControlePNCP"])] == (
            date(2025, 8, 2),
            date(2025, 8, 3),
            date(2025, 8, 4),
        )
    finally:
        _cleanup(engine, scope)


@pytest.mark.integration
def test_approved_snapshot_loads_and_exact_replay_is_noop(engine: Engine) -> None:
    """Catch a load that skips approval, advances incompletely, or rewrites an exact replay."""
    scope = _start_scope(engine)

    try:
        source_watermark = _seed_silver(engine, _records(scope), scope)
        _approve_quality(engine, source_watermark)
        service = WarehouseLoadService(engine)
        with capture_logs() as logs:
            first = service.run_pending()
        before_counts = _gold_counts(engine, scope)
        second = service.run_pending()

        assert first == WarehouseLoadResult(
            status=WarehouseLoadStatus.LOADED,
            source_watermark=source_watermark,
            rows_loaded=2,
            reused=False,
        )
        assert before_counts == (5, 2, 2, 1, 2)
        assert second == WarehouseLoadResult(
            status=WarehouseLoadStatus.NOOP,
            source_watermark=source_watermark,
            rows_loaded=2,
            reused=True,
        )
        assert _gold_counts(engine, scope) == before_counts
        assert _gold_watermark(engine) == source_watermark
        assert {
            "event": "warehouse_load_completed",
            "source_watermark": source_watermark,
            "rows_loaded": 2,
            "log_level": "info",
        } in logs
    finally:
        _cleanup(engine, scope)


@pytest.mark.integration
def test_silver_quality_mismatch_blocks_without_gold_writes(engine: Engine) -> None:
    """Catch Gold loading mutable Silver data that has not passed the current quality gate."""
    scope = _start_scope(engine)

    try:
        with pytest.raises(WarehouseStateError, match="APPROVED_SNAPSHOT_UNAVAILABLE"):
            WarehouseLoadService(engine).run_pending()

        _seed_silver(engine, [_records(scope)[0]], scope)
        with pytest.raises(WarehouseStateError, match="APPROVED_SNAPSHOT_UNAVAILABLE"):
            WarehouseLoadService(engine).run_pending()
        assert _gold_counts(engine, scope) == (0, 0, 0, 0, 0)
    finally:
        _cleanup(engine, scope)


@pytest.mark.integration
def test_later_snapshot_updates_type_one_dimensions_and_fact(engine: Engine) -> None:
    """Catch key churn, stale changes, or timestamps rewritten for an unchanged sibling."""
    scope = _start_scope(engine)
    first_records = _records(scope)

    try:
        first_watermark = _seed_silver(engine, first_records, scope)
        _approve_quality(engine, first_watermark)
        service = WarehouseLoadService(engine)
        service.run_pending()
        with engine.connect() as connection:
            before = {
                row.numero_controle_pncp: row
                for row in connection.execute(
                    sa.select(
                        fact_procurement.c.numero_controle_pncp,
                        dim_organization.c.organization_key,
                        dim_organization.c.updated_at.label("organization_updated_at"),
                        dim_unit.c.unit_key,
                        dim_unit.c.updated_at.label("unit_updated_at"),
                        dim_modality.c.modality_key,
                        fact_procurement.c.procurement_key,
                        fact_procurement.c.source_raw_response_id,
                        fact_procurement.c.normalized_sha256,
                        fact_procurement.c.created_at,
                        fact_procurement.c.updated_at.label("fact_updated_at"),
                    )
                    .select_from(fact_procurement)
                    .join(dim_organization)
                    .join(dim_unit)
                    .join(dim_modality)
                )
            }

        updated = deepcopy(first_records[0])
        updated["orgaoEntidade"]["razaoSocial"] = "Órgão Atualizado"
        updated["unidadeOrgao"]["nomeUnidade"] = "Unidade Atualizada"
        updated["modalidadeNome"] = "Modalidade Atualizada"
        updated["valorTotalEstimado"] = 125.5
        updated["dataAtualizacaoGlobal"] = "2025-10-03T12:00:00"
        second_watermark = _seed_silver(engine, [updated], scope)
        _approve_quality(engine, second_watermark)

        result = service.run_pending()
        with engine.connect() as connection:
            after = {
                row.numero_controle_pncp: row
                for row in connection.execute(
                    sa.select(
                        fact_procurement.c.numero_controle_pncp,
                        dim_organization.c.organization_key,
                        dim_organization.c.orgao_razao_social,
                        dim_organization.c.updated_at.label("organization_updated_at"),
                        dim_unit.c.unit_key,
                        dim_unit.c.nome_unidade,
                        dim_unit.c.updated_at.label("unit_updated_at"),
                        dim_modality.c.modality_key,
                        dim_modality.c.modalidade_nome,
                        fact_procurement.c.procurement_key,
                        fact_procurement.c.source_raw_response_id,
                        fact_procurement.c.normalized_sha256,
                        fact_procurement.c.valor_total_estimado,
                        fact_procurement.c.created_at,
                        fact_procurement.c.updated_at.label("fact_updated_at"),
                    )
                    .select_from(fact_procurement)
                    .join(dim_organization)
                    .join(dim_unit)
                    .join(dim_modality)
                )
            }

        changed_key = updated["numeroControlePNCP"]
        unchanged_key = first_records[1]["numeroControlePNCP"]
        changed_before = before[changed_key]
        changed_after = after[changed_key]
        unchanged_before = before[unchanged_key]
        unchanged_after = after[unchanged_key]

        assert second_watermark > first_watermark
        assert result.source_watermark == second_watermark
        assert changed_after.organization_key == changed_before.organization_key
        assert changed_after.unit_key == changed_before.unit_key
        assert changed_after.modality_key == changed_before.modality_key
        assert changed_after.procurement_key == changed_before.procurement_key
        assert changed_after.orgao_razao_social == "Órgão Atualizado"
        assert changed_after.nome_unidade == "Unidade Atualizada"
        assert changed_after.modalidade_nome == "Modalidade Atualizada"
        assert changed_after.valor_total_estimado == Decimal("125.5000")
        assert changed_after.source_raw_response_id > changed_before.source_raw_response_id
        assert changed_after.normalized_sha256 != changed_before.normalized_sha256
        assert changed_after.created_at == changed_before.created_at
        assert unchanged_after.organization_updated_at == unchanged_before.organization_updated_at
        assert unchanged_after.unit_updated_at == unchanged_before.unit_updated_at
        assert unchanged_after.fact_updated_at == unchanged_before.fact_updated_at
    finally:
        _cleanup(engine, scope)


@pytest.mark.integration
def test_reconciliation_failure_rolls_back_all_gold_changes(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch partial dimension/fact commits or watermark progress after failed reconciliation."""
    scope = _start_scope(engine)
    invalid = ReconciliationResult(
        silver_rows=1,
        fact_rows=0,
        missing_in_fact=1,
        missing_in_silver=0,
        orphan_foreign_keys=0,
        lineage_mismatches=0,
        estimated_silver=Decimal("100.2500"),
        estimated_fact=Decimal("0"),
        estimated_nulls_silver=0,
        estimated_nulls_fact=0,
        homologated_silver=Decimal("300.0000"),
        homologated_fact=Decimal("0"),
        homologated_nulls_silver=0,
        homologated_nulls_fact=0,
    )

    def invalid_reconciliation(
        repository: WarehouseRepository,
        connection: sa.Connection,
    ) -> ReconciliationResult:
        return invalid

    monkeypatch.setattr(WarehouseRepository, "reconcile", invalid_reconciliation)
    try:
        source_watermark = _seed_silver(engine, [_records(scope)[0]], scope)
        _approve_quality(engine, source_watermark)
        with pytest.raises(WarehouseStateError, match="RECONCILIATION_FAILED"):
            WarehouseLoadService(engine).run_pending()
        assert _gold_counts(engine, scope) == (0, 0, 0, 0, 0)
        assert _gold_watermark(engine) == 0
    finally:
        _cleanup(engine, scope)


@pytest.mark.integration
def test_concurrent_loads_serialize_and_second_returns_noop(engine: Engine) -> None:
    """Catch a waiting REPEATABLE READ transaction reusing a stale Gold watermark snapshot."""
    scope = _start_scope(engine)
    source_watermark = _seed_silver(engine, _records(scope), scope)
    _approve_quality(engine, source_watermark)
    lock_connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_connection.execute(
        sa.select(sa.func.pg_advisory_lock(sa.func.hashtext("gold_procurement:procurements")))
    )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(WarehouseLoadService(engine).run_pending) for _ in range(2)]
            _wait_for_advisory_waiters(engine, expected=2)
            lock_connection.execute(
                sa.select(
                    sa.func.pg_advisory_unlock(sa.func.hashtext("gold_procurement:procurements"))
                )
            )
            results = [future.result(timeout=10) for future in futures]

        assert {result.status for result in results} == {
            WarehouseLoadStatus.LOADED,
            WarehouseLoadStatus.NOOP,
        }
        assert {result.source_watermark for result in results} == {source_watermark}
        assert _gold_counts(engine, scope) == (5, 2, 2, 1, 2)
    finally:
        lock_connection.execute(
            sa.select(sa.func.pg_advisory_unlock(sa.func.hashtext("gold_procurement:procurements")))
        )
        lock_connection.close()
        _cleanup(engine, scope)


@pytest.mark.integration
def test_load_works_with_single_connection_pool(engine: Engine) -> None:
    """Catch warehouse locking that deadlocks while requesting a second pooled connection."""
    scope = _start_scope(engine)
    source_watermark = _seed_silver(engine, _records(scope), scope)
    _approve_quality(engine, source_watermark)
    single_connection_engine = create_engine(
        engine.url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
        pool_pre_ping=True,
    )

    try:
        result = WarehouseLoadService(single_connection_engine).run_pending()
        assert result.status is WarehouseLoadStatus.LOADED
        assert result.source_watermark == source_watermark
    finally:
        single_connection_engine.dispose()
        _cleanup(engine, scope)
