# Phase 2 PNCP Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build and verify a resilient, typed PNCP read client that validates official query constraints, retries transient failures, paginates without data loss, and succeeds against the live public API.

**Architecture:** `src/govinsight/extract/pncp` owns the external PNCP boundary. Query models translate typed Python values to the official Portuguese parameter names; the client owns HTTP, safe errors, response validation and retry; pagination remains a separate iterator over validated pages. No data is persisted in this phase.

**Tech Stack:** Python 3.12, HTTPX2, Pydantic 2, Structlog, pytest, official PNCP Consulta API.

## Global Constraints

- Work on `feat/phase-2-pncp-extraction`, based on the verified Phase 1 branch.
- Use only documented PNCP GET endpoints under `https://pncp.gov.br/api/consulta`.
- Contratação page size is 10–50; contrato page size is 10–500; page numbers start at 1.
- Dates are transmitted as `YYYYMMDD` and start date cannot be after end date.
- `codigoModalidadeContratacao` is mandatory and positive for contratação queries.
- Retry only transport/timeouts and HTTP 429, 500, 502, 503, 504.
- Never retry 400, 401, 403, 404 or 422.
- Honor `Retry-After`; otherwise use capped exponential backoff with jitter.
- Do not log response bodies, secrets, supplier identifiers, or full CNPJ filters.
- Preserve response records as dictionaries in this phase; Silver business typing belongs to Phase 4.
- Production behavior follows test-first RED→GREEN cycles.
- RAW persistence, checkpoint tables and watermarks belong to Phase 3.

---

### Task 1: Runtime dependency and PNCP settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/govinsight/config.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: environment variables prefixed with `GOVINSIGHT_PNCP_`.
- Produces: timeout and retry settings used by `PNCPClient.from_settings`.

- [x] **Step 1: Write failing settings validation tests**

Add tests proving zero timeout and zero retry attempts raise `ValidationError`, while defaults are `https://pncp.gov.br/api/consulta`, 30 seconds, 4 attempts, 0.5-second base delay and 8-second cap.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/test_config.py -v`

Expected: new assertions fail because PNCP fields do not exist.

- [x] **Step 3: Implement minimal settings**

Add `pncp_base_url: AnyHttpUrl`, positive timeout, retry attempts, base delay and cap. Move `httpx2>=2.9,<3` from the development group to runtime dependencies because extraction uses it.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/unit/test_config.py -v`

Expected: all configuration tests pass without warnings.

- [x] **Step 5: Commit**

Run: `git add pyproject.toml .env.example src/govinsight/config.py tests/unit/test_config.py && git commit -m "feat: add PNCP client settings"`

### Task 2: Query and page contracts

**Files:**
- Create: `src/govinsight/extract/__init__.py`
- Create: `src/govinsight/extract/pncp/__init__.py`
- Create: `src/govinsight/extract/pncp/models.py`
- Create: `tests/unit/extract/test_pncp_models.py`

**Interfaces:**
- Produces: `ProcurementQuery`, `ContractQuery`, `PNCPPage`, `QueryMode`.
- Consumers: client and pagination tasks.

- [x] **Step 1: Write failing model tests**

Test literal parameter dictionaries for a procurement query and a contract query. Test reversed dates, page zero, procurement sizes 9/51, contract sizes 9/501 and modality zero as validation failures. Test `PNCPPage` rejects inconsistent negative metadata and accepts nullable fields inside records.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/extract/test_pncp_models.py -v`

Expected: collection fails because PNCP models do not exist.

- [x] **Step 3: Implement contracts**

Use frozen Pydantic models. `ProcurementQuery.to_params()` emits `dataInicial`, `dataFinal`, `codigoModalidadeContratacao`, `pagina`, `tamanhoPagina`, plus only non-null official filters. `ContractQuery.to_params()` emits dates/page/size and optional `cnpjOrgao`/unit. `PNCPPage` contains `data`, `totalRegistros`, `totalPaginas`, `numeroPagina`, `paginasRestantes`, `empty` and an `empty_page(page)` constructor.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/unit/extract/test_pncp_models.py -v`

Expected: all contract tests pass.

- [x] **Step 5: Commit**

Run: `git add src/govinsight/extract tests/unit/extract/test_pncp_models.py && git commit -m "feat: model PNCP query and page contracts"`

### Task 3: Retry policy and safe errors

**Files:**
- Create: `src/govinsight/extract/pncp/errors.py`
- Create: `src/govinsight/extract/pncp/retry.py`
- Create: `tests/unit/extract/test_pncp_retry.py`

**Interfaces:**
- Produces: `RetryPolicy.delay_seconds(attempt, retry_after, random_value, now)`, `PNCPError`, `PNCPHTTPError`, `PNCPResponseError`, `PNCPRetryExhausted`.
- Consumer: `PNCPClient`.

- [x] **Step 1: Write failing retry tests**

Assert hand-calculated delays: attempt 1 with base 0.5 and random 0.0 is 0.5; attempt 3 is 2.0; a cap of 1.0 returns 1.0; `Retry-After: 7` returns 7.0; a future HTTP-date returns the UTC delta; malformed/negative `Retry-After` falls back to exponential delay.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/extract/test_pncp_retry.py -v`

Expected: collection fails because the retry module does not exist.

- [x] **Step 3: Implement policy and exceptions**

`RetryPolicy` is frozen and validates positive attempts/delays and jitter in `[0,1]`. The fallback formula is `min(max_delay, base_delay * 2 ** (attempt - 1)) * (1 + jitter_ratio * random_value)`. A valid server delay is honored without applying the client cap. HTTP errors expose status, endpoint and attempt but never a response body.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/unit/extract/test_pncp_retry.py -v`

Expected: all retry/error tests pass.

- [x] **Step 5: Commit**

Run: `git add src/govinsight/extract/pncp/errors.py src/govinsight/extract/pncp/retry.py tests/unit/extract/test_pncp_retry.py && git commit -m "feat: add PNCP retry and error policy"`

### Task 4: HTTP client

**Files:**
- Create: `src/govinsight/extract/pncp/client.py`
- Create: `tests/fixtures/pncp/contratacoes_publicacao_page_1.json`
- Create: `tests/unit/extract/test_pncp_client.py`

**Interfaces:**
- Consumes: query/page contracts, retry policy, Settings and HTTPX2 transport.
- Produces: context-managed `PNCPClient`, `list_procurements`, `list_contracts`, `get_procurement`.

- [x] **Step 1: Add a recorded official fixture**

Store one representative record from the validated 01/08/2025 modalidade 6 response with the real envelope and nullable `valorTotalHomologado`. The fixture is evidence for shape, not invented business data.

- [x] **Step 2: Write failing client tests**

With `httpx2.MockTransport`, assert a 200 fixture becomes `PNCPPage`; 204 becomes an empty page; 400 raises `PNCPHTTPError` after one request; malformed JSON and invalid envelopes raise `PNCPResponseError`; 500 then 429 with `Retry-After: 2` then 200 yields sleep calls `[0.5, 2.0]`; repeated 503 raises `PNCPRetryExhausted`; `get_procurement` returns a dictionary and rejects malformed CNPJ/year/sequence before HTTP.

- [x] **Step 3: Verify RED**

Run: `pytest tests/unit/extract/test_pncp_client.py -v`

Expected: collection fails because the client does not exist.

- [x] **Step 4: Implement minimal client**

Use an injected HTTPX2 client or create one with base URL, timeout and `Accept: application/json`. `_request` logs endpoint/status/attempt/duration only, retries the allowlist, parses JSON and translates validation errors to safe project exceptions. `from_settings` builds `RetryPolicy` from settings. Implement `close`, `__enter__`, and `__exit__` without closing an externally owned client.

- [x] **Step 5: Verify GREEN**

Run: `pytest tests/unit/extract/test_pncp_client.py -v`

Expected: all client tests pass without real sleeping or network.

- [x] **Step 6: Commit**

Run: `git add src/govinsight/extract/pncp/client.py tests/fixtures/pncp tests/unit/extract/test_pncp_client.py && git commit -m "feat: implement resilient PNCP extraction client"`

### Task 5: Pagination without duplication

**Files:**
- Create: `src/govinsight/extract/pncp/pagination.py`
- Create: `tests/unit/extract/test_pncp_pagination.py`

**Interfaces:**
- Consumes: a page fetcher `Callable[[int], PNCPPage]`.
- Produces: `iter_pages(fetch_page, start_page=1)` and `iter_records(fetch_page, start_page=1)`.

- [x] **Step 1: Write failing pagination tests**

Use real `PNCPPage` values for three pages and assert requested pages are `[1,2,3]`, record IDs are yielded once in order, an empty first page stops immediately, and a response whose `numeroPagina` differs from the requested page raises `PNCPResponseError`.

- [x] **Step 2: Verify RED**

Run: `pytest tests/unit/extract/test_pncp_pagination.py -v`

Expected: collection fails because pagination does not exist.

- [x] **Step 3: Implement iterators**

Fetch one page at a time, validate the returned page number, yield it, and stop when `empty`, `paginasRestantes == 0`, or `numeroPagina >= totalPaginas`. `iter_records` delegates to `iter_pages` and yields each record once.

- [x] **Step 4: Verify GREEN**

Run: `pytest tests/unit/extract/test_pncp_pagination.py -v`

Expected: all pagination tests pass.

- [x] **Step 5: Commit**

Run: `git add src/govinsight/extract/pncp/pagination.py tests/unit/extract/test_pncp_pagination.py && git commit -m "feat: add validated PNCP pagination"`

### Task 6: Live API contract gate

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/integration/test_pncp_live.py`

**Interfaces:**
- Consumes: official PNCP endpoint and production client.
- Produces: evidence that the implementation matches the current public API.

- [x] **Step 1: Write the live test**

Mark `live_api`. Query `/v1/contratacoes/publicacao` for 01/08/2025, modality 6, page 1, size 10. Assert 10 records, page 1, non-empty metadata and that every record has non-empty `numeroControlePNCP`, `orgaoEntidade`, `unidadeOrgao`, `objetoCompra`, and `dataAtualizacaoGlobal`.

- [x] **Step 2: Run the live test**

Run: `pytest -p no:cacheprovider tests/integration/test_pncp_live.py -v`

Expected: HTTP 200 and 1 passed. A network outage fails the phase gate; it is not converted to skip.

- [x] **Step 3: Run the complete suite**

Run: `ruff check .; ruff format --check .; pytest -v --cov=govinsight --cov-report=term-missing`

Expected: zero lint/format errors, unit suite green, PostgreSQL test skipped without its URL, live PNCP test green, and coverage at least 80%.

- [x] **Step 4: Commit**

Run: `git add pyproject.toml tests/integration/test_pncp_live.py && git commit -m "test: verify PNCP live API contract"`

### Task 7: Documentation and Phase 2 checkpoint

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-2.md`

**Interfaces:**
- Consumes: fresh test/lint/live API evidence.
- Produces: truthful usage guide and Fase 2 status.

- [x] **Step 1: Document client usage**

Show a bounded one-page procurement query and context manager usage. Document retry status allowlist, page constraints, live test command, safe logging fields and the explicit absence of persistence.

- [x] **Step 2: Re-run final gates**

Run unit coverage locally, the live API test with network permission, and verify `git diff --check`. Record exact counts, coverage, live records and problems in `docs/checkpoints/phase-2.md`.

- [x] **Step 3: Commit documentation**

Run: `git add README.md docs/checkpoints/phase-2.md docs/superpowers/plans/2026-08-17-phase-2-pncp-extraction.md && git commit -m "docs: add PNCP extraction guide and checkpoint"`

- [x] **Step 4: Confirm clean branch**

Run: `git status --short; git log --oneline --decorate -12`

Expected: clean `feat/phase-2-pncp-extraction` with focused commits.
