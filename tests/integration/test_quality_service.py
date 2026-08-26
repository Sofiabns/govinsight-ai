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

from govinsight.quality import service as quality_service_module
from govinsight.quality.models import QualityRunStatus, RuleStatus
from govinsight.quality.repositories import QualityRunRepository
from govinsight.quality.rules import procurement_quality_rules
from govinsight.quality.service import DataQualityExecutionError, DataQualityService
from govinsight.quality.tables import data_quality_result, data_quality_run
from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.raw.tables import etl_run, etl_watermark, raw_api_response
from govinsight.transform.procurement import parse_procurement
from govinsight.transform.repositories import ProcurementRepository, SilverWatermarkRepository
from govinsight.transform.tables import procurement, rejected_record

FIXTURE = Path(__file__).parents[1] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for quality integration tests")
    value = create_engine(database_url, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


def _body(records: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "data": records,
            "totalRegistros": len(records),
            "totalPaginas": 1,
            "numeroPagina": 1,
            "paginasRestantes": 0,
            "empty": not records,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _insert_raw(engine: Engine, records: list[dict[str, object]], identity: str) -> int:
    body = _body(records)
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
            pipeline_name=f"quality-test-{identity}",
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
                record_count=len(records),
                collected_at=datetime.now(UTC),
                duration_ms=1,
            ),
        )
    assert outcome.raw_response_id is not None
    return outcome.raw_response_id


def _load_silver(engine: Engine, records: list[dict[str, object]], identity: str) -> int:
    raw_id = _insert_raw(engine, records, identity)
    with engine.begin() as connection:
        for index, record in enumerate(records):
            parsed = parse_procurement(record, raw_response_id=raw_id, record_index=index)
            assert parsed.procurement is not None
            ProcurementRepository().upsert(connection, parsed.procurement)
        SilverWatermarkRepository().advance(connection, raw_id)
    return raw_id


@pytest.mark.integration
def test_quality_gate_persists_evidence_blocks_invalid_data_and_warns_on_volume(
    engine: Engine,
) -> None:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    identity = uuid4().hex

    with engine.begin() as connection:
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(rejected_record.delete())
        connection.execute(procurement.delete())
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )

    first_raw_id = _load_silver(engine, [base], f"{identity}-clean")
    service = DataQualityService(engine)
    first = service.run_pending()

    assert first.status is QualityRunStatus.PASSED
    assert first.source_watermark == first_raw_id
    assert first.rows_evaluated == 1
    assert first.score == Decimal("100.00")
    assert first.blocking_failures == 0
    assert len([item for item in first.evaluations if item.status is RuleStatus.PASSED]) == 12
    assert first.evaluations[-1].status is RuleStatus.NOT_EVALUATED

    replay = service.run_pending()
    assert replay.run_id == first.run_id
    assert replay.reused is True
    with engine.connect() as connection:
        result_count = connection.execute(
            sa.select(sa.func.count()).select_from(data_quality_result)
        ).scalar_one()
    assert result_count == 13

    invalid = deepcopy(base)
    invalid["numeroControlePNCP"] = "13183513000127-1-000147/2025"
    invalid_raw_id = _load_silver(engine, [invalid], f"{identity}-invalid")
    with engine.begin() as connection:
        connection.execute(
            procurement.update()
            .where(procurement.c.numero_controle_pncp == invalid["numeroControlePNCP"])
            .values(
                numero_controle_pncp="broken-key",
                objeto_compra="",
                uf_sigla="ZZ",
                informacao_complementar="SENSITIVE-VALUE",
            )
        )

    failed = service.run_pending()
    failed_by_code = {item.rule_code: item for item in failed.evaluations}
    assert failed.status is QualityRunStatus.FAILED
    assert failed.source_watermark == invalid_raw_id
    assert failed_by_code["REQUIRED_TEXT_PRESENT"].status is RuleStatus.FAILED
    assert failed_by_code["UF_DOMAIN_VALID"].status is RuleStatus.FAILED
    assert failed_by_code["PURCHASE_YEAR_CONSISTENT"].status is RuleStatus.FAILED
    assert "SENSITIVE-VALUE" not in str(failed.model_dump())
    with engine.connect() as connection:
        quality_watermark = connection.execute(
            sa.select(etl_watermark.c.watermark_value).where(
                etl_watermark.c.pipeline_name == "data_quality",
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == "quality",
            )
        ).scalar_one()
    assert quality_watermark == {"last_raw_response_id": first_raw_id}

    corrected = deepcopy(invalid)
    corrected["dataAtualizacaoGlobal"] = "2025-09-18T13:50:39"
    corrected["objetoCompra"] = "OBJETO CORRIGIDO"
    corrected["unidadeOrgao"]["ufSigla"] = "RS"
    with engine.begin() as connection:
        connection.execute(
            procurement.delete().where(procurement.c.numero_controle_pncp == "broken-key")
        )
    corrected_raw_id = _load_silver(engine, [corrected], f"{identity}-corrected")
    corrected_result = service.run_pending()
    assert corrected_result.status is QualityRunStatus.PASSED
    assert corrected_result.source_watermark == corrected_raw_id
    with engine.connect() as connection:
        corrected_watermark = connection.execute(
            sa.select(etl_watermark.c.watermark_value).where(
                etl_watermark.c.pipeline_name == "data_quality",
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage == "quality",
            )
        ).scalar_one()
    assert corrected_watermark == {"last_raw_response_id": corrected_raw_id}

    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            data_quality_run.insert(),
            [
                {
                    "dataset": "procurements",
                    "stage": "quality",
                    "source_watermark": corrected_raw_id + offset,
                    "status": "PASSED",
                    "started_at": now,
                    "finished_at": now,
                    "rows_evaluated": 1,
                    "score": Decimal("100.00"),
                    "blocking_failures": 0,
                }
                for offset in (1_000_000, 1_000_001)
            ],
        )

    extras: list[dict[str, object]] = []
    for sequence in (148, 149):
        extra = deepcopy(base)
        extra["numeroControlePNCP"] = f"13183513000127-1-{sequence:06d}/2025"
        extras.append(extra)
    volume_raw_id = _load_silver(engine, extras, f"{identity}-volume")
    volume_result = service.run_pending()
    volume = {item.rule_code: item for item in volume_result.evaluations}["ROW_VOLUME_ANOMALY"]
    assert volume_result.status is QualityRunStatus.PASSED
    assert volume_result.source_watermark == volume_raw_id
    assert volume.status is RuleStatus.WARNING
    assert volume.details == {
        "baseline_median": 1,
        "deviation_percent": Decimal("300.00"),
        "history_runs": 4,
    }

    with engine.begin() as connection:
        run_ids = sa.select(etl_run.c.id).where(
            etl_run.c.pipeline_name.like(f"quality-test-{identity}%")
        )
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(procurement.delete())
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(run_ids)))
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )


@pytest.mark.integration
def test_replay_read_failure_never_reclassifies_completed_evidence(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    identity = uuid4().hex
    with engine.begin() as connection:
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(procurement.delete())
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )

    _load_silver(engine, [base], f"{identity}-clean")
    service = DataQualityService(engine)
    completed = service.run_pending()
    assert completed.run_id is not None

    def fail_load(connection: sa.Connection, run_id: int) -> object:
        raise sa.exc.OperationalError("SELECT", {}, RuntimeError("SENSITIVE-DB-CONTEXT"))

    monkeypatch.setattr(service._runs, "load", fail_load)
    with pytest.raises(DataQualityExecutionError, match="QUALITY_QUERY_FAILED") as captured:
        service.run_pending()
    assert "SENSITIVE-DB-CONTEXT" not in str(captured.value)

    with engine.begin() as connection:
        stored = connection.execute(
            sa.select(data_quality_run.c.status, data_quality_run.c.error_code).where(
                data_quality_run.c.id == completed.run_id
            )
        ).one()
        changed = QualityRunRepository().fail_execution(
            connection,
            completed.run_id,
            "QUALITY_QUERY_FAILED",
        )
    assert stored.status == "PASSED"
    assert stored.error_code is None
    assert changed is False

    with engine.begin() as connection:
        run_ids = sa.select(etl_run.c.id).where(
            etl_run.c.pipeline_name.like(f"quality-test-{identity}%")
        )
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(procurement.delete())
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(run_ids)))
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )


@pytest.mark.integration
def test_quality_rules_share_one_repeatable_read_snapshot(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    identity = uuid4().hex
    with engine.begin() as connection:
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(procurement.delete())
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )

    first_raw_id = _load_silver(engine, [base], f"{identity}-first")
    concurrent = deepcopy(base)
    concurrent["numeroControlePNCP"] = "13183513000127-1-000150/2025"
    concurrent_raw_id = _insert_raw(engine, [concurrent], f"{identity}-concurrent")
    parsed = parse_procurement(concurrent, raw_response_id=concurrent_raw_id, record_index=0)
    assert parsed.procurement is not None
    rules = procurement_quality_rules()

    def rules_with_concurrent_commit() -> object:
        yield rules[0]
        with engine.begin() as connection:
            ProcurementRepository().upsert(connection, parsed.procurement)
            SilverWatermarkRepository().advance(connection, concurrent_raw_id)
        yield from rules[1:]

    monkeypatch.setattr(
        quality_service_module,
        "procurement_quality_rules",
        rules_with_concurrent_commit,
    )
    first = DataQualityService(engine).run_pending()
    by_code = {item.rule_code: item for item in first.evaluations}
    assert first.status is QualityRunStatus.PASSED
    assert first.source_watermark == first_raw_id
    assert first.rows_evaluated == 1
    assert by_code["REQUIRED_TEXT_PRESENT"].checked_count == 1

    monkeypatch.undo()
    second = DataQualityService(engine).run_pending()
    assert second.status is QualityRunStatus.PASSED
    assert second.source_watermark == concurrent_raw_id
    assert second.rows_evaluated == 2

    with engine.begin() as connection:
        run_ids = sa.select(etl_run.c.id).where(
            etl_run.c.pipeline_name.like(f"quality-test-{identity}%")
        )
        connection.execute(data_quality_result.delete())
        connection.execute(data_quality_run.delete())
        connection.execute(procurement.delete())
        connection.execute(
            raw_api_response.delete().where(raw_api_response.c.etl_run_id.in_(run_ids))
        )
        connection.execute(etl_run.delete().where(etl_run.c.id.in_(run_ids)))
        connection.execute(
            etl_watermark.delete().where(
                etl_watermark.c.dataset == "procurements",
                etl_watermark.c.stage.in_(["silver", "quality"]),
            )
        )
