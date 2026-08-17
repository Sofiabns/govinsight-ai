import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx2
import pytest

from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.errors import PNCPHTTPError, PNCPResponseError, PNCPRetryExhausted
from govinsight.extract.pncp.models import ProcurementQuery
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
) -> PNCPClient:
    http_client = httpx2.Client(
        base_url="https://pncp.gov.br/api/consulta",
        transport=httpx2.MockTransport(handler),
    )
    return PNCPClient(
        http_client=http_client,
        retry_policy=policy or RetryPolicy(jitter_ratio=0.0),
        sleep=sleep or (lambda _seconds: None),
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
