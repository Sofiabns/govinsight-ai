from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class NormalizedProcurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    numero_controle_pncp: str
    source_raw_response_id: Annotated[int, Field(gt=0)]
    source_record_index: Annotated[int, Field(ge=0)]
    normalized_sha256: Sha256
    srp: bool
    orgao_cnpj: str
    orgao_razao_social: str
    poder_id: str | None
    esfera_id: str | None
    ano_compra: Annotated[int, Field(gt=0)]
    sequencial_compra: Annotated[int, Field(gt=0)]
    numero_compra: str | None
    codigo_unidade: str
    nome_unidade: str
    codigo_ibge: str | None
    municipio_nome: str | None
    uf_sigla: str | None
    uf_nome: str | None
    amparo_legal_codigo: int | None
    amparo_legal_nome: str | None
    amparo_legal_descricao: str | None
    modalidade_id: Annotated[int, Field(gt=0)]
    modalidade_nome: str
    modo_disputa_id: int | None
    modo_disputa_nome: str | None
    situacao_compra_id: int | None
    situacao_compra_nome: str | None
    tipo_instrumento_codigo: int | None
    tipo_instrumento_nome: str | None
    data_inclusao: datetime | None
    data_publicacao_pncp: datetime
    data_atualizacao: datetime | None
    data_atualizacao_global: datetime
    data_abertura_proposta: datetime | None
    data_encerramento_proposta: datetime | None
    processo: str | None
    objeto_compra: str
    informacao_complementar: str | None
    link_sistema_origem: str | None
    link_processo_eletronico: str | None
    justificativa_presencial: str | None
    usuario_nome: str | None
    valor_total_estimado: Decimal | None
    valor_total_homologado: Decimal | None


class RejectedProcurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_raw_response_id: Annotated[int, Field(gt=0)]
    source_record_index: Annotated[int, Field(ge=0)]
    natural_key: str | None
    error_codes: tuple[str, ...]
    transformer_version: str = "1"


class ProcurementParseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    procurement: NormalizedProcurement | None = None
    rejection: RejectedProcurement | None = None

    @model_validator(mode="after")
    def require_exactly_one_result(self) -> "ProcurementParseResult":
        if (self.procurement is None) == (self.rejection is None):
            raise ValueError("parse result requires exactly one outcome")
        return self

