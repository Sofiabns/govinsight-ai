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

from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.raw.tables import etl_watermark, raw_api_response
from govinsight.transform.procurement import parse_procurement
from govinsight.transform.repositories import ProcurementRepository, SilverWatermarkRepository
from govinsight.transform.tables import procurement
from govinsight.warehouse.models import ReconciliationResult
from govinsight.warehouse.repositories import WarehouseRepository
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
        connection.execute(procurement.delete())
        connection.execute(etl_watermark.delete().where(etl_watermark.c.dataset == "procurements"))
        connection.execute(raw_api_response.delete())


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
