import random
import re
import time
from collections.abc import Callable
from typing import Any, Self

import httpx2
from pydantic import ValidationError

from govinsight.config import Settings
from govinsight.extract.pncp.errors import PNCPHTTPError, PNCPResponseError, PNCPRetryExhausted
from govinsight.extract.pncp.models import ContractQuery, PNCPPage, ProcurementQuery, QueryMode
from govinsight.extract.pncp.retry import RetryPolicy
from govinsight.observability.logging import get_logger

TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
CNPJ_PATTERN = re.compile(r"^\d{14}$")


class PNCPClient:
    def __init__(
        self,
        *,
        http_client: httpx2.Client | None = None,
        base_url: str = "https://pncp.gov.br/api/consulta",
        timeout: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._owns_client = http_client is None
        self._client = http_client or httpx2.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._random_value = random_value
        self._logger = get_logger(__name__)

    @classmethod
    def from_settings(cls, settings: Settings) -> "PNCPClient":
        return cls(
            base_url=str(settings.pncp_base_url),
            timeout=settings.pncp_timeout_seconds,
            retry_policy=RetryPolicy(
                max_attempts=settings.pncp_retry_max_attempts,
                base_delay=settings.pncp_retry_base_delay_seconds,
                max_delay=settings.pncp_retry_max_delay_seconds,
            ),
        )

    def list_procurements(self, query: ProcurementQuery) -> PNCPPage:
        endpoint = f"/v1/contratacoes/{query.mode.value}"
        payload = self._request_json(endpoint, params=query.to_params())
        if payload is None:
            return PNCPPage.empty_page(query.page)
        try:
            return PNCPPage.model_validate(payload)
        except ValidationError as exc:
            raise PNCPResponseError(endpoint=endpoint, reason="invalid page envelope") from exc

    def list_contracts(self, query: ContractQuery) -> PNCPPage:
        endpoint = "/v1/contratos"
        if query.mode is QueryMode.UPDATE:
            endpoint += "/atualizacao"
        payload = self._request_json(endpoint, params=query.to_params())
        if payload is None:
            return PNCPPage.empty_page(query.page)
        try:
            return PNCPPage.model_validate(payload)
        except ValidationError as exc:
            raise PNCPResponseError(endpoint=endpoint, reason="invalid page envelope") from exc

    def get_procurement(self, cnpj: str, year: int, sequence: int) -> dict[str, Any]:
        if not CNPJ_PATTERN.fullmatch(cnpj):
            raise ValueError("cnpj must contain exactly 14 digits")
        if not 2021 <= year <= 9999:
            raise ValueError("year must be between 2021 and 9999")
        if sequence < 1:
            raise ValueError("sequence must be positive")

        endpoint = f"/v1/orgaos/{cnpj}/compras/{year}/{sequence}"
        payload = self._request_json(endpoint)
        if not isinstance(payload, dict):
            raise PNCPResponseError(endpoint=endpoint, reason="expected an object")
        return payload

    def _request_json(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> Any:
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            started_at = time.perf_counter()
            try:
                response = self._client.get(endpoint, params=params)
            except httpx2.TransportError as exc:
                self._logger.warning(
                    "pncp_transport_error",
                    endpoint=endpoint,
                    attempt=attempt,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
                )
                if attempt == self._retry_policy.max_attempts:
                    raise PNCPRetryExhausted(endpoint=endpoint, attempts=attempt) from exc
                self._wait_before_retry(attempt)
                continue

            self._logger.info(
                "pncp_response",
                endpoint=endpoint,
                status_code=response.status_code,
                attempt=attempt,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 3),
            )
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt == self._retry_policy.max_attempts:
                    raise PNCPRetryExhausted(endpoint=endpoint, attempts=attempt)
                self._wait_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            if response.status_code >= 400:
                raise PNCPHTTPError(
                    status_code=response.status_code,
                    endpoint=endpoint,
                    attempt=attempt,
                )
            if response.status_code == 204:
                return None
            try:
                return response.json()
            except (ValueError, TypeError) as exc:
                raise PNCPResponseError(endpoint=endpoint, reason="malformed JSON") from exc

        raise PNCPRetryExhausted(endpoint=endpoint, attempts=self._retry_policy.max_attempts)

    def _wait_before_retry(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._retry_policy.delay_seconds(
            attempt,
            retry_after=retry_after,
            random_value=self._random_value(),
        )
        self._sleep(delay)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
