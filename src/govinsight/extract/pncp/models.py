from datetime import date
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QueryMode(StrEnum):
    PUBLICATION = "publicacao"
    UPDATE = "atualizacao"


class _DateWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_date: date
    end_date: date
    page: int = Field(default=1, ge=1)
    mode: QueryMode = QueryMode.PUBLICATION

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    def _common_params(self) -> dict[str, str | int]:
        return {
            "dataInicial": self.start_date.strftime("%Y%m%d"),
            "dataFinal": self.end_date.strftime("%Y%m%d"),
            "pagina": self.page,
            "tamanhoPagina": self.page_size,
        }


class ProcurementQuery(_DateWindow):
    modality_code: int = Field(gt=0)
    page_size: int = Field(default=50, ge=10, le=50)
    organization_cnpj: str | None = Field(default=None, pattern=r"^\d{14}$")
    administrative_unit_code: str | None = None

    def to_params(self) -> dict[str, str | int]:
        params = self._common_params()
        params["codigoModalidadeContratacao"] = self.modality_code
        if self.organization_cnpj is not None:
            params["cnpj"] = self.organization_cnpj
        if self.administrative_unit_code is not None:
            params["codigoUnidadeAdministrativa"] = self.administrative_unit_code
        return params


class ContractQuery(_DateWindow):
    page_size: int = Field(default=500, ge=10, le=500)
    organization_cnpj: str | None = Field(default=None, pattern=r"^\d{14}$")
    administrative_unit_code: str | None = None

    def to_params(self) -> dict[str, str | int]:
        params = self._common_params()
        if self.organization_cnpj is not None:
            params["cnpjOrgao"] = self.organization_cnpj
        if self.administrative_unit_code is not None:
            params["codigoUnidadeAdministrativa"] = self.administrative_unit_code
        return params


class PNCPPage(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    data: list[dict[str, Any]]
    total_records: int = Field(alias="totalRegistros", ge=0)
    total_pages: int = Field(alias="totalPaginas", ge=0)
    page_number: int = Field(alias="numeroPagina", ge=1)
    remaining_pages: int = Field(alias="paginasRestantes", ge=0)
    empty: bool

    @classmethod
    def empty_page(cls, page_number: int) -> "PNCPPage":
        return cls(
            data=[],
            total_records=0,
            total_pages=0,
            page_number=page_number,
            remaining_pages=0,
            empty=True,
        )
