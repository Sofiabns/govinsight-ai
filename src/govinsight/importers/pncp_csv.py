import argparse
import csv
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from govinsight.analytics import AnalyticsService
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.quality import DataQualityService, QualityRunStatus
from govinsight.raw.hashing import request_fingerprint, sha256_text
from govinsight.raw.models import RawCapture, RawDataset, RunStatus
from govinsight.raw.repositories import RawResponseRepository, RunRepository
from govinsight.transform import SilverTransformationService
from govinsight.warehouse import WarehouseLoadService

SOURCE_URL = "https://repositorio.dados.gov.br/seges/comprasgov/anual/2025/"
NATURAL_KEY = re.compile(r"^[0-9]{14}-[0-9]-[0-9]{6}/[0-9]{4}$")


def _value(row: dict[str, str], name: str) -> str | None:
    value = (row.get(name) or "").strip()
    return value or None


def to_pncp_record(row: dict[str, str]) -> dict[str, Any] | None:
    control_number = _value(row, "numero_controle_PNCP")
    publication_date = _value(row, "data_publicacao_pncp")
    if (
        control_number is None
        or not NATURAL_KEY.fullmatch(control_number)
        or publication_date is None
    ):
        return None
    updated = _value(row, "data_atualizacao_pncp")
    return {
        "numeroControlePNCP": control_number,
        "srp": (_value(row, "srp") or "false").casefold() == "true",
        "orgaoEntidade": {
            "cnpj": _value(row, "orgao_entidade_cnpj"),
            "razaoSocial": _value(row, "orgao_entidade_razao_social"),
            "esferaId": _value(row, "orgao_entidade_esfera_id"),
            "poderId": _value(row, "orgao_entidade_poder_id"),
        },
        "unidadeOrgao": {
            "codigoUnidade": _value(row, "unidade_orgao_codigo_unidade"),
            "nomeUnidade": _value(row, "unidade_orgao_nome_unidade"),
            "codigoIbge": _value(row, "unidade_orgao_codigo_ibge"),
            "municipioNome": _value(row, "unidade_orgao_municipio_nome"),
            "ufSigla": _value(row, "unidade_orgao_uf_sigla"),
            "ufNome": _value(row, "unidade_orgao_uf_nome"),
        },
        "amparoLegal": {
            "codigo": _value(row, "amparo_legal_codigo_pncp"),
            "nome": _value(row, "amparo_legal_nome"),
            "descricao": _value(row, "amparo_legal_descricao"),
        },
        "anoCompra": _value(row, "ano_compra_pncp"),
        "sequencialCompra": _value(row, "sequencial_compra_pncp"),
        "numeroCompra": _value(row, "numero_compra"),
        "modalidadeId": _value(row, "modalidade_id_pncp"),
        "modalidadeNome": _value(row, "modalidade_nome"),
        "modoDisputaId": _value(row, "modo_disputa_id_pncp"),
        "modoDisputaNome": _value(row, "modo_disputa_nome_pncp"),
        "situacaoCompraId": _value(row, "situacao_compra_id_pncp"),
        "situacaoCompraNome": _value(row, "situacao_compra_nome_pncp"),
        "tipoInstrumentoConvocatorioCodigo": _value(
            row, "tipo_instrumento_convocatorio_codigo_pncp"
        ),
        "tipoInstrumentoConvocatorioNome": _value(row, "tipo_instrumento_convocatorio_nome"),
        "dataInclusao": _value(row, "data_inclusao_pncp"),
        "dataPublicacaoPncp": publication_date,
        "dataAtualizacao": updated,
        "dataAtualizacaoGlobal": updated,
        "dataAberturaProposta": _value(row, "data_abertura_proposta_pncp"),
        "dataEncerramentoProposta": _value(row, "data_encerramento_proposta_pncp"),
        "processo": _value(row, "processo"),
        "objetoCompra": _value(row, "objeto_compra"),
        "informacaoComplementar": _value(row, "informacao_complementar"),
        "linkSistemaOrigem": _value(row, "link_sistema_origem"),
        "justificativaPresencial": _value(row, "justificativa_presencial"),
        "usuarioNome": _value(row, "usuario_nome"),
        "valorTotalEstimado": _value(row, "valor_total_estimado"),
        "valorTotalHomologado": _value(row, "valor_total_homologado"),
    }


def import_csv(path: Path, limit: int) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        records: list[dict[str, Any]] = []
        for row in csv.DictReader(stream):
            converted = to_pncp_record(row)
            if converted is not None:
                records.append(converted)
            if len(records) >= limit:
                break
    if not records:
        raise ValueError("CSV does not contain valid procurement records")

    dates = [date.fromisoformat(record["dataPublicacaoPncp"][:10]) for record in records]
    envelope = {
        "data": records,
        "totalRegistros": len(records),
        "totalPaginas": 1,
        "numeroPagina": 1,
        "paginasRestantes": 0,
        "empty": False,
    }
    raw_body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    settings = Settings()
    engine = create_database_engine(settings)
    runs = RunRepository()
    responses = RawResponseRepository()
    params = {"file": path.name, "record_limit": limit}
    endpoint = f"{SOURCE_URL}{path.name}"
    try:
        with engine.begin() as connection:
            run_id = runs.create(
                connection, "comprasgov_csv_raw", RawDataset.PROCUREMENTS, "publicacao"
            )
            capture = RawCapture(
                etl_run_id=run_id,
                source="comprasgov_csv",
                dataset=RawDataset.PROCUREMENTS,
                endpoint=endpoint,
                request_params=params,
                request_fingerprint=request_fingerprint(
                    "comprasgov_csv", RawDataset.PROCUREMENTS.value, endpoint, params
                ),
                window_start=min(dates),
                window_end=max(dates),
                page_number=1,
                http_status=200,
                raw_body=raw_body,
                body_sha256=sha256_text(raw_body),
                record_count=len(records),
                collected_at=datetime.now(UTC),
                duration_ms=0,
            )
            inserted = responses.insert(connection, capture).inserted
            runs.apply_page(connection, run_id, len(records), inserted)
            runs.finish(connection, run_id, RunStatus.SUCCEEDED)

        silver_service = SilverTransformationService(engine)
        silver_records = 0
        while True:
            batch = silver_service.transform_pending(limit=20)
            if batch.responses_processed == 0:
                break
            silver_records += batch.inserted + batch.updated
        quality = DataQualityService(engine).run_pending()
        if quality.status not in {QualityRunStatus.PASSED, QualityRunStatus.NOOP}:
            raise RuntimeError("official CSV did not pass the Gold quality gate")
        warehouse = WarehouseLoadService(engine).run_pending()
        summary = AnalyticsService(engine).summary()
        return {
            "source_records": len(records),
            "silver_records": silver_records,
            "quality": quality.status,
            "gold_rows_loaded": warehouse.rows_loaded,
            "dashboard_records": summary.procurement_count,
        }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an official Compras.gov PNCP CSV export")
    parser.add_argument("path", type=Path)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()
    print(json.dumps(import_csv(args.path, args.limit), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
