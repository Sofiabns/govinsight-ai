import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from govinsight.quality.repositories import QualityWatermarkRepository
from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.raw.tables import etl_watermark, raw_api_response
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


def _records() -> list[dict[str, object]]:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    first = deepcopy(base)
    first["valorTotalEstimado"] = 100.25
    first["valorTotalHomologado"] = 300

    second = deepcopy(base)
    second["numeroControlePNCP"] = "99999999000199-1-000002/2025"
    second["orgaoEntidade"] = {
        "cnpj": "99999999000199",
        "razaoSocial": "Órgão Dois",
        "poderId": "E",
        "esferaId": "M",
    }
    second["unidadeOrgao"] = {
        "codigoUnidade": "U2",
        "nomeUnidade": "Unidade Dois",
        "codigoIbge": "3550308",
        "municipioNome": "São Paulo",
        "ufSigla": "SP",
        "ufNome": "São Paulo",
    }
    second["sequencialCompra"] = 2
    second["dataPublicacaoPncp"] = "2025-08-02T10:00:00"
    second["dataAberturaProposta"] = "2025-08-03T10:00:00"
    second["dataEncerramentoProposta"] = "2025-08-04T10:00:00"
    second["dataAtualizacaoGlobal"] = "2025-08-02T11:00:00"
    second["valorTotalEstimado"] = 250
    second["valorTotalHomologado"] = None
    return [first, second]


def _insert_raw(engine: Engine, records: list[dict[str, object]]) -> int:
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
    return outcome.raw_response_id


def _seed_silver(engine: Engine, records: list[dict[str, object]]) -> int:
    raw_id = _insert_raw(engine, records)
    with engine.begin() as connection:
        for index, record in enumerate(records):
            parsed = parse_procurement(record, raw_response_id=raw_id, record_index=index)
            assert parsed.procurement is not None
            ProcurementRepository().upsert(connection, parsed.procurement)
        SilverWatermarkRepository().advance(connection, raw_id)
    return raw_id


def _cleanup(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(fact_procurement.delete())
        connection.execute(dim_date.delete())
        connection.execute(dim_modality.delete())
        connection.execute(dim_unit.delete())
        connection.execute(dim_organization.delete())
        connection.execute(rejected_record.delete())
        connection.execute(procurement.delete())
        connection.execute(etl_watermark.delete().where(etl_watermark.c.dataset == "procurements"))
        connection.execute(raw_api_response.delete())


def _approve_quality(engine: Engine, raw_id: int) -> None:
    with engine.begin() as connection:
        QualityWatermarkRepository().advance(connection, raw_id)


def _gold_counts(engine: Engine) -> tuple[int, int, int, int, int]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (dim_date, dim_organization, dim_unit, dim_modality, fact_procurement)
        )


def _gold_watermark(engine: Engine) -> int:
    with engine.connect() as connection:
        return WarehouseWatermarkRepository().read_state(connection, lock_gold=False).gold


@pytest.mark.integration
def test_repository_builds_reconciled_star(engine: Engine) -> None:
    """Catch broken grains, dimension joins, lineage, date roles, or money reconciliation."""
    _cleanup(engine)
    _seed_silver(engine, _records())
    repository = WarehouseRepository()

    try:
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
            joined = connection.execute(
                sa.select(
                    fact_procurement.c.numero_controle_pncp,
                    dim_organization.c.orgao_cnpj,
                    dim_unit.c.codigo_unidade,
                    dim_modality.c.modalidade_id,
                    dim_date.c.full_date,
                )
                .join(dim_organization)
                .join(dim_unit)
                .join(dim_modality)
                .join(dim_date, fact_procurement.c.publication_date_key == dim_date.c.date_key)
                .order_by(fact_procurement.c.numero_controle_pncp)
            ).all()
        assert len(joined) == 2
        assert {row.full_date for row in joined} == {date(2025, 8, 1), date(2025, 8, 2)}
    finally:
        _cleanup(engine)


@pytest.mark.integration
def test_approved_snapshot_loads_and_exact_replay_is_noop(engine: Engine) -> None:
    """Catch a load that skips approval, advances incompletely, or rewrites an exact replay."""
    _cleanup(engine)
    source_watermark = _seed_silver(engine, _records())
    _approve_quality(engine, source_watermark)

    try:
        service = WarehouseLoadService(engine)
        first = service.run_pending()
        before_counts = _gold_counts(engine)
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
        assert _gold_counts(engine) == before_counts
        assert _gold_watermark(engine) == source_watermark
    finally:
        _cleanup(engine)


@pytest.mark.integration
def test_silver_quality_mismatch_blocks_without_gold_writes(engine: Engine) -> None:
    """Catch Gold loading mutable Silver data that has not passed the current quality gate."""
    _cleanup(engine)
    _seed_silver(engine, [_records()[0]])

    try:
        with pytest.raises(WarehouseStateError, match="UNAPPROVED_SILVER_SNAPSHOT"):
            WarehouseLoadService(engine).run_pending()
        assert _gold_counts(engine) == (0, 0, 0, 0, 0)
        assert _gold_watermark(engine) == 0
    finally:
        _cleanup(engine)


@pytest.mark.integration
def test_later_snapshot_updates_type_one_dimensions_and_fact(engine: Engine) -> None:
    """Catch surrogate-key churn or stale descriptions, measures, and lineage on later snapshots."""
    _cleanup(engine)
    first_record = _records()[0]
    first_watermark = _seed_silver(engine, [first_record])
    _approve_quality(engine, first_watermark)

    try:
        service = WarehouseLoadService(engine)
        service.run_pending()
        with engine.connect() as connection:
            before = connection.execute(
                sa.select(
                    dim_organization.c.organization_key,
                    dim_unit.c.unit_key,
                    dim_modality.c.modality_key,
                    fact_procurement.c.procurement_key,
                    fact_procurement.c.source_raw_response_id,
                    fact_procurement.c.normalized_sha256,
                    fact_procurement.c.created_at,
                )
                .select_from(fact_procurement)
                .join(dim_organization)
                .join(dim_unit)
                .join(dim_modality)
            ).one()

        updated = deepcopy(first_record)
        updated["orgaoEntidade"]["razaoSocial"] = "Órgão Atualizado"
        updated["unidadeOrgao"]["nomeUnidade"] = "Unidade Atualizada"
        updated["modalidadeNome"] = "Modalidade Atualizada"
        updated["valorTotalEstimado"] = 125.5
        updated["dataAtualizacaoGlobal"] = "2025-10-03T12:00:00"
        second_watermark = _seed_silver(engine, [updated])
        _approve_quality(engine, second_watermark)

        result = service.run_pending()
        with engine.connect() as connection:
            after = connection.execute(
                sa.select(
                    dim_organization.c.organization_key,
                    dim_organization.c.orgao_razao_social,
                    dim_unit.c.unit_key,
                    dim_unit.c.nome_unidade,
                    dim_modality.c.modality_key,
                    dim_modality.c.modalidade_nome,
                    fact_procurement.c.procurement_key,
                    fact_procurement.c.source_raw_response_id,
                    fact_procurement.c.normalized_sha256,
                    fact_procurement.c.valor_total_estimado,
                    fact_procurement.c.created_at,
                )
                .select_from(fact_procurement)
                .join(dim_organization)
                .join(dim_unit)
                .join(dim_modality)
            ).one()

        assert second_watermark > first_watermark
        assert result.source_watermark == second_watermark
        assert after.organization_key == before.organization_key
        assert after.unit_key == before.unit_key
        assert after.modality_key == before.modality_key
        assert after.procurement_key == before.procurement_key
        assert after.orgao_razao_social == "Órgão Atualizado"
        assert after.nome_unidade == "Unidade Atualizada"
        assert after.modalidade_nome == "Modalidade Atualizada"
        assert after.valor_total_estimado == Decimal("125.5000")
        assert after.source_raw_response_id > before.source_raw_response_id
        assert after.normalized_sha256 != before.normalized_sha256
        assert after.created_at == before.created_at
    finally:
        _cleanup(engine)


@pytest.mark.integration
def test_reconciliation_failure_rolls_back_all_gold_changes(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch partial dimension/fact commits or watermark progress after failed reconciliation."""
    _cleanup(engine)
    source_watermark = _seed_silver(engine, [_records()[0]])
    _approve_quality(engine, source_watermark)
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
        with pytest.raises(WarehouseStateError, match="RECONCILIATION_FAILED"):
            WarehouseLoadService(engine).run_pending()
        assert _gold_counts(engine) == (0, 0, 0, 0, 0)
        assert _gold_watermark(engine) == 0
    finally:
        _cleanup(engine)
