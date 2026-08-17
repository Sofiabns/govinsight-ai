import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest

from govinsight.extract.pncp import FetchedPNCPPage
from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.errors import PNCPHTTPError, PNCPResponseError, PNCPRetryExhausted
from govinsight.extract.pncp.models import ContractQuery, PNCPPage, ProcurementQuery, QueryMode
from govinsight.extract.pncp.retry import RetryPolicy

FIXTURE = Path(__file__).parents[2] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"


def procurement_query() -> ProcurementQuery:
    return ProcurementQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        modality_code=6,
        page_size=10,
    )


def client_for(
    handler: Any,
    *,
    policy: RetryPolicy | None = None,
    sleep: Any = None,
    monotonic: Any = None,
    utc_now: Any = None,
) -> PNCPClient:
    http_client = httpx2.Client(
        base_url="https://pncp.gov.br/api/consulta",
        transport=httpx2.MockTransport(handler),
    )
    clock_dependencies = {}
    if monotonic is not None:
        clock_dependencies["monotonic"] = monotonic
    if utc_now is not None:
        clock_dependencies["utc_now"] = utc_now
    return PNCPClient(
        http_client=http_client,
        retry_policy=policy or RetryPolicy(jitter_ratio=0.0),
        sleep=sleep or (lambda _seconds: None),
        **clock_dependencies,
    )


def test_list_procurements_parses_recorded_official_page() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/consulta/v1/contratacoes/publicacao"
        assert request.url.params["codigoModalidadeContratacao"] == "6"
        return httpx2.Response(200, json=payload)

    with client_for(handler) as client:
        page = client.list_procurements(procurement_query())

    assert page.total_records == 1
    assert page.data[0]["numeroControlePNCP"] == "13183513000127-1-000146/2025"
    assert page.data[0]["valorTotalHomologado"] is None


def test_no_content_becomes_an_empty_requested_page() -> None:
    query = procurement_query().model_copy(update={"page": 3})

    with client_for(lambda _request: httpx2.Response(204)) as client:
        page = client.list_procurements(query)

    assert page.empty is True
    assert page.page_number == 3


def test_fetch_procurements_preserves_exact_http_response_metadata() -> None:
    raw_body = '{ "data": [], "totalRegistros": 0, "totalPaginas": 0, '
    raw_body += '"numeroPagina": 1, "paginasRestantes": 0, "empty": true }\n'
    query = procurement_query()
    monotonic_values = iter([10.000, 10.125])
    collected_at = datetime(2025, 8, 1, 12, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/consulta/v1/contratacoes/publicacao"
        assert dict(request.url.params) == {
            "dataInicial": "20250801",
            "dataFinal": "20250801",
            "pagina": "1",
            "tamanhoPagina": "10",
            "codigoModalidadeContratacao": "6",
        }
        return httpx2.Response(200, content=raw_body.encode("utf-8"))

    with client_for(
        handler,
        monotonic=lambda: next(monotonic_values),
        utc_now=lambda: collected_at,
    ) as client:
        fetched = client.fetch_procurements(query)

    assert isinstance(fetched, FetchedPNCPPage)
    assert fetched.raw_body == raw_body
    assert fetched.status_code == 200
    assert fetched.duration_ms == 125.0
    assert fetched.endpoint == "/v1/contratacoes/publicacao"
    assert fetched.request_params == {
        "dataInicial": "20250801",
        "dataFinal": "20250801",
        "pagina": 1,
        "tamanhoPagina": 10,
        "codigoModalidadeContratacao": 6,
    }
    assert fetched.collected_at == collected_at
    assert fetched.page == PNCPPage.empty_page(1)


def test_fetch_procurements_preserves_no_content_response_metadata() -> None:
    query = procurement_query().model_copy(update={"page": 3})

    with client_for(
        lambda _request: httpx2.Response(204),
        monotonic=iter([4.0, 4.05]).__next__,
        utc_now=lambda: datetime(2025, 8, 1, 12, 0, tzinfo=UTC),
    ) as client:
        fetched = client.fetch_procurements(query)

    assert fetched.raw_body == ""
    assert fetched.status_code == 204
    assert fetched.page == PNCPPage.empty_page(3)


@pytest.mark.parametrize(
    ("mode", "expected_path"),
    [
        (QueryMode.PUBLICATION, "/api/consulta/v1/contratos"),
        (QueryMode.UPDATE, "/api/consulta/v1/contratos/atualizacao"),
    ],
)
def test_list_contracts_uses_the_official_endpoint_for_each_mode(
    mode: QueryMode, expected_path: str
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == expected_path
        assert request.url.params["tamanhoPagina"] == "10"
        return httpx2.Response(200, json=payload)

    query = ContractQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        page_size=10,
        mode=mode,
    )
    with client_for(handler) as client:
        page = client.list_contracts(query)

    assert page.total_records == 1


@pytest.mark.parametrize(
    ("mode", "expected_endpoint"),
    [
        (QueryMode.PUBLICATION, "/v1/contratos"),
        (QueryMode.UPDATE, "/v1/contratos/atualizacao"),
    ],
)
def test_fetch_contracts_preserves_endpoint_for_each_mode(
    mode: QueryMode, expected_endpoint: str
) -> None:
    raw_body = '{ "data": [], "totalRegistros": 0, "totalPaginas": 0, '
    raw_body += '"numeroPagina": 1, "paginasRestantes": 0, "empty": true }\n'
    query = ContractQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        page_size=10,
        mode=mode,
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == f"/api/consulta{expected_endpoint}"
        return httpx2.Response(200, content=raw_body.encode("utf-8"))

    with client_for(handler) as client:
        fetched = client.fetch_contracts(query)

    assert fetched.endpoint == expected_endpoint
    assert fetched.raw_body == raw_body
    assert fetched.page == PNCPPage.empty_page(1)


def test_terminal_client_error_is_not_retried() -> None:
    requests = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(400, text="sensitive body")

    with client_for(handler) as client, pytest.raises(PNCPHTTPError) as caught:
        client.list_procurements(procurement_query())

    assert requests == 1
    assert "sensitive body" not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, content=b"not-json"),
        httpx2.Response(200, json={"data": []}),
    ],
)
def test_invalid_response_is_translated_to_safe_domain_error(response: httpx2.Response) -> None:
    with client_for(lambda _request: response) as client, pytest.raises(PNCPResponseError):
        client.list_procurements(procurement_query())


def test_transient_responses_use_backoff_and_retry_after_before_success() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    responses = iter(
        [
            httpx2.Response(500),
            httpx2.Response(429, headers={"Retry-After": "2"}),
            httpx2.Response(200, json=payload),
        ]
    )
    sleeps: list[float] = []

    with client_for(lambda _request: next(responses), sleep=sleeps.append) as client:
        page = client.list_procurements(procurement_query())

    assert page.total_records == 1
    assert sleeps == [0.5, 2.0]


def test_repeated_transient_status_exhausts_bounded_attempts() -> None:
    requests = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(503)

    policy = RetryPolicy(max_attempts=3, jitter_ratio=0.0)
    with client_for(handler, policy=policy) as client, pytest.raises(PNCPRetryExhausted):
        client.list_procurements(procurement_query())

    assert requests == 3


def test_transport_failure_is_retried_before_success() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx2.ConnectError("connection unavailable", request=request)
        return httpx2.Response(200, json=payload)

    with client_for(handler, sleep=sleeps.append) as client:
        page = client.list_procurements(procurement_query())

    assert page.total_records == 1
    assert attempts == 2
    assert sleeps == [0.5]


def test_get_procurement_returns_detail_dictionary() -> None:
    payload = {"numeroControlePNCP": "83551549000100-1-000027/2025", "anoCompra": 2025}

    with client_for(lambda _request: httpx2.Response(200, json=payload)) as client:
        result = client.get_procurement("83551549000100", 2025, 27)

    assert result == payload


@pytest.mark.parametrize(
    ("cnpj", "year", "sequence"),
    [("123", 2025, 1), ("83551549000100", 2020, 1), ("83551549000100", 2025, 0)],
)
def test_get_procurement_rejects_malformed_identifier_before_http(
    cnpj: str, year: int, sequence: int
) -> None:
    requests = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(200, json={})

    with client_for(handler) as client, pytest.raises(ValueError):
        client.get_procurement(cnpj, year, sequence)

    assert requests == 0
