from datetime import date

import pytest
from pydantic import ValidationError

from govinsight.extract.pncp.models import ContractQuery, PNCPPage, ProcurementQuery, QueryMode


def test_procurement_query_emits_official_parameter_names() -> None:
    query = ProcurementQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 2),
        modality_code=6,
        page=2,
        page_size=10,
        organization_cnpj="00394460000141",
    )

    assert query.mode is QueryMode.PUBLICATION
    assert query.to_params() == {
        "dataInicial": "20250801",
        "dataFinal": "20250802",
        "codigoModalidadeContratacao": 6,
        "pagina": 2,
        "tamanhoPagina": 10,
        "cnpjOrgao": "00394460000141",
    }


def test_contract_query_omits_filters_that_are_not_supplied() -> None:
    query = ContractQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        page=1,
        page_size=500,
        mode=QueryMode.UPDATE,
    )

    assert query.to_params() == {
        "dataInicial": "20250801",
        "dataFinal": "20250801",
        "pagina": 1,
        "tamanhoPagina": 500,
    }


@pytest.mark.parametrize(
    "query",
    [
        ProcurementQuery,
        ContractQuery,
    ],
)
def test_queries_reject_reversed_date_windows(query: type[ProcurementQuery | ContractQuery]) -> None:
    kwargs = {
        "start_date": date(2025, 8, 2),
        "end_date": date(2025, 8, 1),
    }
    if query is ProcurementQuery:
        kwargs["modality_code"] = 6

    with pytest.raises(ValidationError):
        query(**kwargs)


@pytest.mark.parametrize(
    ("query", "overrides"),
    [
        (ProcurementQuery, {"page": 0}),
        (ProcurementQuery, {"page_size": 9}),
        (ProcurementQuery, {"page_size": 51}),
        (ProcurementQuery, {"modality_code": 0}),
        (ContractQuery, {"page": 0}),
        (ContractQuery, {"page_size": 9}),
        (ContractQuery, {"page_size": 501}),
    ],
)
def test_queries_reject_values_outside_pncp_limits(
    query: type[ProcurementQuery | ContractQuery], overrides: dict[str, int]
) -> None:
    kwargs = {
        "start_date": date(2025, 8, 1),
        "end_date": date(2025, 8, 1),
        **overrides,
    }
    if query is ProcurementQuery and "modality_code" not in kwargs:
        kwargs["modality_code"] = 6

    with pytest.raises(ValidationError):
        query(**kwargs)


def test_page_accepts_nullable_business_fields_without_rewriting_them() -> None:
    page = PNCPPage.model_validate(
        {
            "data": [{"numeroControlePNCP": "ABC-1-2025", "valorTotalHomologado": None}],
            "totalRegistros": 1,
            "totalPaginas": 1,
            "numeroPagina": 1,
            "paginasRestantes": 0,
            "empty": False,
        }
    )

    assert page.data[0]["valorTotalHomologado"] is None
    assert page.total_records == 1
    assert page.page_number == 1


@pytest.mark.parametrize("field", ["totalRegistros", "totalPaginas", "paginasRestantes"])
def test_page_rejects_negative_metadata(field: str) -> None:
    payload = {
        "data": [],
        "totalRegistros": 0,
        "totalPaginas": 0,
        "numeroPagina": 1,
        "paginasRestantes": 0,
        "empty": True,
    }
    payload[field] = -1

    with pytest.raises(ValidationError):
        PNCPPage.model_validate(payload)


def test_empty_page_preserves_requested_page_number() -> None:
    page = PNCPPage.empty_page(3)

    assert page.data == []
    assert page.page_number == 3
    assert page.empty is True
