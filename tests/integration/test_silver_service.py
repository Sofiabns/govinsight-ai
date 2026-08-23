import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.raw.tables import etl_run, etl_watermark, raw_api_response
from govinsight.transform.repositories import SilverWatermarkRepository
from govinsight.transform.service import SilverTransformationService
from govinsight.transform.tables import procurement, rejected_record

FIXTURE = Path(__file__).parents[1] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for Silver integration tests")
    value = create_engine(database_url, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


def _body(*records: dict[str, object]) -> str:
    envelope = {
        "data": records,
        "totalRegistros": len(records),
        "totalPaginas": 1,
        "numeroPagina": 1,
        "paginasRestantes": 0,
        "empty": not records,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def _insert_raw(engine: Engine, body: str, identity: str) -> int:
    params = {
        "dataFinal": "20250801",
        "dataInicial": "20250801",
        "codigoModalidadeContratacao": 6,
        "pagina": 1,
        "tamanhoPagina": 10,
    }
    endpoint = f"/v1/contratacoes/publicacao/{identity}"
    with engine.begin() as connection:
        run_id = RunRepository().create(
            connection,
            pipeline_name=f"silver-test-{identity}",
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
                window_end=date(2025, 8, 1),
                page_number=1,
                http_status=200,
                raw_body=body,
                body_sha256=sha256_text(body),
                record_count=len(json.loads(body)["data"]),
                collected_at=datetime.now(UTC),
                duration_ms=1,
            ),
        )
    assert outcome.raw_response_id is not None
    return outcome.raw_response_id


@pytest.mark.integration
def test_silver_flow_quarantines_replays_updates_and_never_regresses(engine: Engine) -> None:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    invalid = deepcopy(base)
    invalid["orgaoEntidade"]["cnpj"] = "invalid"
    identity = uuid4().hex

    with engine.begin() as connection:
        connection.execute(rejected_record.delete())
        connection.execute(procurement.delete())
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.pipeline_name == "silver_procurement",
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == "silver",
            )
        )
        last_existing_raw_id = connection.execute(
            sa.select(sa.func.coalesce(sa.func.max(raw_api_response.c.id), 0))
        ).scalar_one()
        SilverWatermarkRepository().advance(connection, last_existing_raw_id)

    first_raw_id = _insert_raw(engine, _body(base, invalid), f"{identity}-a")
    service = SilverTransformationService(engine)
    first = service.transform_pending()

    assert first.model_dump() == {
        "responses_processed": 1,
        "records_received": 2,
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "rejected": 1,
        "last_raw_response_id": first_raw_id,
    }
    with engine.connect() as connection:
        stored = connection.execute(sa.select(procurement)).mappings().one()
        rejection = connection.execute(sa.select(rejected_record)).mappings().one()
    assert stored["source_raw_response_id"] == first_raw_id
    assert stored["objeto_compra"] == base["objetoCompra"]
    assert rejection["error_codes"] == ["INVALID_CNPJ"]
    assert "invalid" not in str(rejection)

    assert service.transform_pending().responses_processed == 0

    newer = deepcopy(base)
    newer["dataAtualizacaoGlobal"] = "2025-09-17T13:50:39"
    newer["objetoCompra"] = "OBJETO ATUALIZADO"
    second_raw_id = _insert_raw(engine, _body(newer), f"{identity}-b")
    second = service.transform_pending()
    assert (second.updated, second.last_raw_response_id) == (1, second_raw_id)

    older = deepcopy(base)
    older["dataAtualizacaoGlobal"] = "2025-09-01T13:50:39"
    older["objetoCompra"] = "OBJETO ANTIGO"
    third_raw_id = _insert_raw(engine, _body(older), f"{identity}-c")
    third = service.transform_pending()
    assert (third.unchanged, third.last_raw_response_id) == (1, third_raw_id)
    with engine.connect() as connection:
        final = connection.execute(sa.select(procurement)).mappings().one()
    assert final["objeto_compra"] == "OBJETO ATUALIZADO"
    assert final["source_raw_response_id"] == second_raw_id

    too_large = deepcopy(base)
    too_large["numeroControlePNCP"] = "13183513000127-1-000147/2025"
    too_large["valorTotalEstimado"] = "100000000000000000000"
    failing_raw_id = _insert_raw(engine, _body(too_large), f"{identity}-d")
    with pytest.raises(sa.exc.DataError):
        service.transform_pending()
    with engine.connect() as connection:
        watermark = connection.execute(
            sa.select(etl_watermark.c.watermark_value).where(
                etl_watermark.c.pipeline_name == "silver_procurement",
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == "silver",
            )
        ).scalar_one()
        failed_key_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(procurement)
            .where(procurement.c.numero_controle_pncp == too_large["numeroControlePNCP"])
        ).scalar_one()
    assert watermark == {"last_raw_response_id": third_raw_id}
    assert failed_key_count == 0
    assert failing_raw_id > third_raw_id

    with engine.begin() as connection:
        run_ids = sa.select(etl_run.c.id).where(
            etl_run.c.pipeline_name.like(f"silver-test-{identity}%")
        )
        connection.execute(rejected_record.delete())
        connection.execute(procurement.delete())
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(run_ids)))
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.pipeline_name == "silver_procurement",
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == "silver",
            )
        )
