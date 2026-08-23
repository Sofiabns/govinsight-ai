import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import NormalizedProcurement, ProcurementParseResult, RejectedProcurement

CNPJ_PATTERN = re.compile(r"^[0-9]{14}$")
IBGE_PATTERN = re.compile(r"^[0-9]{7}$")
NATURAL_KEY_PATTERN = re.compile(r"^[0-9]{14}-[0-9]-[0-9]{6}/[0-9]{4}$")
UF_PATTERN = re.compile(r"^[A-Z]{2}$")
MAX_POSTGRES_INTEGER = 2_147_483_647
MAX_MONEY = Decimal("999999999999999.9999")
MONEY_QUANTUM = Decimal("0.0001")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: object, errors: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("INVALID_TEXT")
        return None
    return value.strip() or None


def _required_text(value: object, errors: list[str]) -> str | None:
    result = _optional_text(value, errors)
    if result is None and "INVALID_TEXT" not in errors:
        errors.append("MISSING_REQUIRED")
    return result


def _integer(value: object, errors: list[str], *, required: bool = False) -> int | None:
    if value is None:
        if required:
            errors.append("MISSING_REQUIRED")
        return None
    if isinstance(value, bool):
        errors.append("INVALID_ID")
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        errors.append("INVALID_ID")
        return None
    if (
        not decimal_value.is_finite()
        or decimal_value != decimal_value.to_integral_value()
        or not 0 < decimal_value <= MAX_POSTGRES_INTEGER
    ):
        errors.append("INVALID_ID")
        return None
    return int(decimal_value)


def _datetime(value: object, errors: list[str], *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            errors.append("MISSING_REQUIRED")
        return None
    if not isinstance(value, str):
        errors.append("INVALID_DATE")
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        errors.append("INVALID_DATE")
        return None
    if result.tzinfo is not None:
        errors.append("INVALID_DATE")
        return None
    return result


def _decimal(value: object, errors: list[str]) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        errors.append("INVALID_DECIMAL")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors.append("INVALID_DECIMAL")
        return None
    try:
        fits_scale = result == result.quantize(MONEY_QUANTUM)
    except InvalidOperation:
        fits_scale = False
    if not result.is_finite() or result < 0 or result > MAX_MONEY or not fits_scale:
        errors.append("INVALID_DECIMAL")
        return None
    return result


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _normalized_hash(values: Mapping[str, object]) -> str:
    canonical = {key: _canonical_value(value) for key, value in values.items()}
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_procurement(
    record: object,
    *,
    raw_response_id: int,
    record_index: int,
) -> ProcurementParseResult:
    if not isinstance(record, Mapping):
        return ProcurementParseResult(
            rejection=RejectedProcurement(
                source_raw_response_id=raw_response_id,
                source_record_index=record_index,
                natural_key=None,
                error_codes=("MALFORMED_RECORD",),
            )
        )

    errors: list[str] = []
    organization = _mapping(record.get("orgaoEntidade"))
    unit = _mapping(record.get("unidadeOrgao"))
    legal_basis = _mapping(record.get("amparoLegal"))
    natural_key_value = _optional_text(record.get("numeroControlePNCP"), errors)
    natural_key = natural_key_value
    if natural_key is not None and not NATURAL_KEY_PATTERN.fullmatch(natural_key):
        errors.append("INVALID_NATURAL_KEY")
        natural_key = None
    cnpj = _required_text(organization.get("cnpj"), errors)
    if cnpj is not None and not CNPJ_PATTERN.fullmatch(cnpj):
        errors.append("INVALID_CNPJ")
    ibge = _optional_text(unit.get("codigoIbge"), errors)
    if ibge is not None and not IBGE_PATTERN.fullmatch(ibge):
        errors.append("INVALID_IBGE")
    uf = _optional_text(unit.get("ufSigla"), errors)
    uf = uf.upper() if uf else None
    if uf is not None and not UF_PATTERN.fullmatch(uf):
        errors.append("INVALID_UF")
    opening = _datetime(record.get("dataAberturaProposta"), errors)
    closing = _datetime(record.get("dataEncerramentoProposta"), errors)
    if opening is not None and closing is not None and closing < opening:
        errors.append("INCONSISTENT_DATE_RANGE")
    srp = record.get("srp")
    if not isinstance(srp, bool):
        errors.append("INVALID_BOOLEAN")
        srp = False

    business: dict[str, object] = {
        "numero_controle_pncp": natural_key,
        "srp": srp,
        "orgao_cnpj": cnpj,
        "orgao_razao_social": _required_text(organization.get("razaoSocial"), errors),
        "poder_id": _optional_text(organization.get("poderId"), errors),
        "esfera_id": _optional_text(organization.get("esferaId"), errors),
        "ano_compra": _integer(record.get("anoCompra"), errors, required=True),
        "sequencial_compra": _integer(record.get("sequencialCompra"), errors, required=True),
        "numero_compra": _optional_text(record.get("numeroCompra"), errors),
        "codigo_unidade": _required_text(unit.get("codigoUnidade"), errors),
        "nome_unidade": _required_text(unit.get("nomeUnidade"), errors),
        "codigo_ibge": ibge,
        "municipio_nome": _optional_text(unit.get("municipioNome"), errors),
        "uf_sigla": uf,
        "uf_nome": _optional_text(unit.get("ufNome"), errors),
        "amparo_legal_codigo": _integer(legal_basis.get("codigo"), errors),
        "amparo_legal_nome": _optional_text(legal_basis.get("nome"), errors),
        "amparo_legal_descricao": _optional_text(legal_basis.get("descricao"), errors),
        "modalidade_id": _integer(record.get("modalidadeId"), errors, required=True),
        "modalidade_nome": _required_text(record.get("modalidadeNome"), errors),
        "modo_disputa_id": _integer(record.get("modoDisputaId"), errors),
        "modo_disputa_nome": _optional_text(record.get("modoDisputaNome"), errors),
        "situacao_compra_id": _integer(record.get("situacaoCompraId"), errors),
        "situacao_compra_nome": _optional_text(record.get("situacaoCompraNome"), errors),
        "tipo_instrumento_codigo": _integer(
            record.get("tipoInstrumentoConvocatorioCodigo"), errors
        ),
        "tipo_instrumento_nome": _optional_text(
            record.get("tipoInstrumentoConvocatorioNome"), errors
        ),
        "data_inclusao": _datetime(record.get("dataInclusao"), errors),
        "data_publicacao_pncp": _datetime(record.get("dataPublicacaoPncp"), errors, required=True),
        "data_atualizacao": _datetime(record.get("dataAtualizacao"), errors),
        "data_atualizacao_global": _datetime(
            record.get("dataAtualizacaoGlobal"), errors, required=True
        ),
        "data_abertura_proposta": opening,
        "data_encerramento_proposta": closing,
        "processo": _optional_text(record.get("processo"), errors),
        "objeto_compra": _required_text(record.get("objetoCompra"), errors),
        "informacao_complementar": _optional_text(record.get("informacaoComplementar"), errors),
        "link_sistema_origem": _optional_text(record.get("linkSistemaOrigem"), errors),
        "link_processo_eletronico": _optional_text(record.get("linkProcessoEletronico"), errors),
        "justificativa_presencial": _optional_text(record.get("justificativaPresencial"), errors),
        "usuario_nome": _optional_text(record.get("usuarioNome"), errors),
        "valor_total_estimado": _decimal(record.get("valorTotalEstimado"), errors),
        "valor_total_homologado": _decimal(record.get("valorTotalHomologado"), errors),
    }
    if natural_key_value is None and "INVALID_TEXT" not in errors:
        errors.append("MISSING_REQUIRED")
    if errors:
        return ProcurementParseResult(
            rejection=RejectedProcurement(
                source_raw_response_id=raw_response_id,
                source_record_index=record_index,
                natural_key=natural_key,
                error_codes=tuple(sorted(set(errors))),
            )
        )

    normalized_sha256 = _normalized_hash(business)
    return ProcurementParseResult(
        procurement=NormalizedProcurement(
            source_raw_response_id=raw_response_id,
            source_record_index=record_index,
            normalized_sha256=normalized_sha256,
            **business,
        )
    )
