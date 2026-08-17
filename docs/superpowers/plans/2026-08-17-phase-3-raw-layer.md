# Phase 3 RAW Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Persist exact successful PNCP page responses in an immutable, idempotent and resumable PostgreSQL Bronze layer with auditable run metadata.

**Architecture:** Extend the PNCP boundary with an enriched page result that preserves response text and request metadata. A transactional ingestion service coordinates small SQLAlchemy Core repositories for RAW responses, run state and extraction checkpoints; PostgreSQL uniqueness provides concurrency-safe idempotency.

**Tech Stack:** Python 3.12, Pydantic 2, HTTPX2 2.10, SQLAlchemy 2, psycopg 3, Alembic 1, PostgreSQL 16, pytest 9 and Docker Compose.

## Global Constraints

- Python must remain `>=3.12,<3.14`; no new runtime dependency is required.
- Store `response.text` as text and hash exactly `raw_body.encode("utf-8")`.
- Persist only successful HTTP 2xx responses; never store or log an error response body.
- Bronze is insert-only through application repositories.
- Identical request identity plus identical body hash creates no second Bronze row.
- A changed body for the same request creates a new immutable version.
- One page transaction atomically applies RAW insertion, run counters and checkpoint progress.
- `control.etl_watermark` is created but not inserted or advanced in Phase 3.
- Scope fingerprints exclude only `pagina`; `tamanhoPagina` remains part of the scope.
- Existing Phase 2 `list_procurements` and `list_contracts` behavior must remain compatible.
- Tests are written and observed failing before production code is added.
- The full design contract is `docs/superpowers/specs/2026-08-17-phase-3-raw-layer-design.md`.

---

### Task 1: Deterministic RAW identities and domain models

**Files:**
- Create: `src/govinsight/raw/__init__.py`
- Create: `src/govinsight/raw/hashing.py`
- Create: `src/govinsight/raw/models.py`
- Create: `tests/unit/raw/test_hashing.py`
- Create: `tests/unit/raw/test_models.py`

**Interfaces:**
- Consumes: parameter mappings produced by `ProcurementQuery.to_params()` and `ContractQuery.to_params()`.
- Produces: `canonical_json(value) -> str`, `sha256_text(value) -> str`, `request_fingerprint(source, dataset, endpoint, params) -> str`, `scope_parameters(params) -> dict`, `scope_fingerprint(...) -> str`, `RawDataset`, `RunStatus`, `RawCapture`, `InsertOutcome`, and `IngestionResult`.

- [x] **Step 1: Write failing hashing tests with literal expectations**

```python
def test_canonical_json_is_stable_and_preserves_unicode() -> None:
    assert canonical_json({"b": 2, "a": "ação"}) == '{"a":"ação","b":2}'


def test_sha256_text_hashes_the_exact_utf8_text() -> None:
    assert sha256_text("GovInsight RAW") == (
        "b42000b4e95d43430479235c411e488cec11d733892b9000a2e434887744e2c3"
    )


def test_scope_keeps_page_size_but_removes_page_number() -> None:
    assert scope_parameters({"pagina": 9, "tamanhoPagina": 50, "dataInicial": "20250801"}) == {
        "tamanhoPagina": 50,
        "dataInicial": "20250801",
    }
```

Also assert that two dictionaries with opposite insertion order produce the same request and
scope fingerprints, while changing `tamanhoPagina` changes the scope fingerprint.

- [x] **Step 2: Run the hashing tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/raw/test_hashing.py -v -p no:cacheprovider`

Expected: collection fails with `ModuleNotFoundError: No module named 'govinsight.raw'`.

- [x] **Step 3: Implement deterministic hashing**

```python
import hashlib
import json
from collections.abc import Mapping

ParameterValue = str | int


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scope_parameters(params: Mapping[str, ParameterValue]) -> dict[str, ParameterValue]:
    return {key: value for key, value in params.items() if key != "pagina"}
```

Build request fingerprints from a canonical object containing `source`, `dataset`, `endpoint`
and a copied parameter dictionary. Build scope fingerprints from the same object after calling
`scope_parameters`.

- [x] **Step 4: Verify hashing GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/raw/test_hashing.py -v -p no:cacheprovider`

Expected: every hashing test passes.

- [x] **Step 5: Write failing domain-model tests**

Create literal UTC datetimes and assert that `RawCapture` accepts a valid 200 response but rejects:

```python
@pytest.mark.parametrize(
    ("field", "value"),
    [("page_number", 0), ("http_status", 199), ("duration_ms", -0.001), ("record_count", -1)],
)
def test_raw_capture_rejects_invalid_metadata(field: str, value: int | float) -> None:
    with pytest.raises(ValidationError):
        RawCapture(**{**VALID_CAPTURE, field: value})
```

Assert `window_end < window_start`, uppercase/short hashes and naive `collected_at` are rejected.
Assert `InsertOutcome(inserted=False, raw_response_id=None)` and a frozen `IngestionResult` carry
literal counters without mutation.

- [x] **Step 6: Run model tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/raw/test_models.py -v -p no:cacheprovider`

Expected: import fails because `govinsight.raw.models` does not exist.

- [x] **Step 7: Implement frozen validated models**

Use Pydantic `BaseModel` with `ConfigDict(frozen=True)` for `RawCapture`, `InsertOutcome` and
`IngestionResult`. Define:

```python
class RawDataset(StrEnum):
    PROCUREMENTS = "procurements"
    CONTRACTS = "contracts"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
```

`RawCapture` contains every `bronze.raw_api_response` application field from the approved design,
including UUID `etl_run_id`, dates, exact text, hashes and validated UTC collection time. Validate
hashes against `^[0-9a-f]{64}$` and reject reversed windows.

`InsertOutcome` contains `inserted: bool` and `raw_response_id: int | None`. `IngestionResult`
contains `run_id: UUID`, `status: RunStatus`, `pages_processed`, `records_received`,
`records_inserted`, and `records_duplicate`, with all counters constrained to non-negative values.

- [x] **Step 8: Verify Task 1 GREEN and refactor**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/raw -v -p no:cacheprovider`

Expected: all Task 1 tests pass without warnings.

- [x] **Step 9: Commit Task 1**

```powershell
git add src/govinsight/raw tests/unit/raw
git commit -m "feat: add deterministic raw capture identities"
```

---

### Task 2: Preserve exact HTTP responses at the PNCP boundary

**Files:**
- Modify: `src/govinsight/extract/pncp/models.py`
- Modify: `src/govinsight/extract/pncp/client.py`
- Modify: `src/govinsight/extract/pncp/__init__.py`
- Modify: `tests/unit/extract/test_pncp_client.py`

**Interfaces:**
- Consumes: existing `ProcurementQuery`, `ContractQuery`, `PNCPPage` and retry behavior.
- Produces: frozen `FetchedPNCPPage`; `PNCPClient.fetch_procurements(query) -> FetchedPNCPPage`; `PNCPClient.fetch_contracts(query) -> FetchedPNCPPage`.

- [x] **Step 1: Write failing enriched-response tests**

Add a handler returning deliberately spaced JSON:

```python
raw_body = '{ "data": [], "totalRegistros": 0, "totalPaginas": 0, '
raw_body += '"numeroPagina": 1, "paginasRestantes": 0, "empty": true }\n'


def handler(_request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, content=raw_body.encode("utf-8"))
```

Inject a monotonic iterator returning `10.000` then `10.125` and a UTC clock returning
`2025-08-01T12:00:00Z`. Assert `fetch_procurements` returns the exact `raw_body`, status 200,
duration `125.0`, official endpoint/params, exact collection time and a validated empty page.
Add a 204 test asserting empty text, status 204 and requested page number. Add contract-mode tests
asserting the root and `/atualizacao` endpoints.

- [x] **Step 2: Run enriched-response tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/extract/test_pncp_client.py -v -p no:cacheprovider`

Expected: tests fail because `fetch_procurements`, `fetch_contracts` and `FetchedPNCPPage` are
missing.

- [x] **Step 3: Add `FetchedPNCPPage` and refactor the request boundary**

Define this frozen Pydantic model:

```python
class FetchedPNCPPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: PNCPPage
    raw_body: str
    endpoint: str
    request_params: dict[str, str | int]
    status_code: int = Field(ge=200, le=299)
    duration_ms: float = Field(ge=0)
    collected_at: datetime
```

Add injectable `monotonic: Callable[[], float]` and `utc_now: Callable[[], datetime]` constructor
arguments. Replace `_request_json` with a private result that retains `response.text`, parsed JSON,
status and final-attempt duration. Do not retain or expose error bodies.

`fetch_procurements` and `fetch_contracts` validate the envelope and build `FetchedPNCPPage`.
Existing list methods become:

```python
def list_procurements(self, query: ProcurementQuery) -> PNCPPage:
    return self.fetch_procurements(query).page
```

Apply the equivalent delegation for contracts.

- [x] **Step 4: Verify GREEN and Phase 2 compatibility**

Run: `.\.venv\Scripts\python.exe -m pytest tests/unit/extract/test_pncp_client.py tests/unit/extract/test_pncp_models.py -v -p no:cacheprovider`

Expected: enriched tests and all existing client/model tests pass.

- [x] **Step 5: Commit Task 2**

```powershell
git add src/govinsight/extract/pncp tests/unit/extract/test_pncp_client.py
git commit -m "feat: preserve exact PNCP response metadata"
```

---

### Task 3: RAW and control database migration

**Files:**
- Create: `alembic/versions/20260817_0002_create_raw_control_tables.py`
- Create: `src/govinsight/raw/tables.py`
- Create: `tests/integration/test_raw_migration.py`

**Interfaces:**
- Consumes: revision `20260817_0001`, PostgreSQL connection from `GOVINSIGHT_DATABASE_URL`.
- Produces: SQLAlchemy Core tables `etl_run`, `raw_api_response`, `extraction_checkpoint`, `etl_watermark`; Alembic revision `20260817_0002`.

- [x] **Step 1: Write the failing real-PostgreSQL migration test**

Mark the test `integration`. With an explicit database URL, run `alembic upgrade head`, inspect
the `bronze` and `control` schemas and assert these exact names:

```python
assert set(inspector.get_table_names(schema="bronze")) >= {"raw_api_response"}
assert set(inspector.get_table_names(schema="control")) >= {
    "etl_run",
    "extraction_checkpoint",
    "etl_watermark",
}
```

Assert the RAW unique constraint is named `uq_raw_response_identity_body`, the FK is named
`fk_raw_response_etl_run`, and check constraints exist for statuses, counters, hashes, HTTP 2xx,
dates and positive pages. In a `try/finally`, downgrade to `20260817_0001`, assert the four tables
are absent, then upgrade back to `head` so the shared development stack is left ready.

- [x] **Step 2: Run migration test and verify RED**

Run with the Compose PostgreSQL URL:

```powershell
$env:GOVINSIGHT_DATABASE_URL = "postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:5432/govinsight?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_raw_migration.py -v -p no:cacheprovider
```

Expected: test fails because revision `20260817_0002` and the four tables do not exist.

- [x] **Step 3: Implement the migration and matching Core tables**

Create tables in this order: `control.etl_run`, `control.extraction_checkpoint`,
`control.etl_watermark`, `bronze.raw_api_response`. Use the exact columns and rules in the design.
The watermark table has `pipeline_name`, `dataset` and `stage` as its composite primary key, plus
nullable `watermark_value` JSONB and `confirmed_at` timestamptz.
Use named constraints:

```python
sa.CheckConstraint(
    "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
    name="ck_etl_run_status",
)
sa.CheckConstraint(
    "(status = 'RUNNING' AND finished_at IS NULL) OR "
    "(status IN ('SUCCEEDED', 'FAILED') AND finished_at IS NOT NULL)",
    name="ck_etl_run_terminal_time",
)
sa.UniqueConstraint(
    "source",
    "dataset",
    "endpoint",
    "request_fingerprint",
    "body_sha256",
    name="uq_raw_response_identity_body",
)
```

Add non-negative counter checks, lowercase hexadecimal hash checks, `window_end >= window_start`,
`page_number > 0`, `http_status BETWEEN 200 AND 299`, non-negative record count/duration, dataset
and mode checks, and the named FK. Add an index on `(dataset, collected_at)`.

`downgrade()` drops only the four Phase 3 tables in reverse dependency order and leaves all four
schemas intact. Mirror the migration columns in `raw/tables.py` using a module-level `MetaData`.

- [x] **Step 4: Verify migration GREEN**

Run the same migration test command.

Expected: upgrade, schema assertions, downgrade and restoration to head all pass.

- [x] **Step 5: Commit Task 3**

```powershell
git add alembic/versions/20260817_0002_create_raw_control_tables.py src/govinsight/raw/tables.py tests/integration/test_raw_migration.py
git commit -m "feat: create bronze raw and control tables"
```

---

### Task 4: Transactional RAW repositories

**Files:**
- Create: `src/govinsight/raw/repositories.py`
- Create: `tests/integration/test_raw_repositories.py`

**Interfaces:**
- Consumes: SQLAlchemy `Connection`, Task 1 domain models and Task 3 Core tables.
- Produces: `RawResponseRepository.insert`, `RunRepository.create/apply_page/finish`, and `CheckpointRepository.next_page/advance`.

- [x] **Step 1: Write failing repository integration tests**

Use a real PostgreSQL connection and the recorded official fixture. Build a `RawCapture` whose
`raw_body` is the exact file text. Assert:

```python
first = raw_repository.insert(connection, capture)
second = raw_repository.insert(connection, capture.model_copy(update={"etl_run_id": second_run}))

assert first.inserted is True
assert first.raw_response_id is not None
assert second == InsertOutcome(inserted=False, raw_response_id=None)
```

Add explicit tests showing a changed body/hash creates a second row and a selected stored body
round-trips with identical UTF-8 bytes. Test run counters after one inserted and one duplicate
page. Test incomplete checkpoint `next_page` returns `last_successful_page + 1`, while a completed
checkpoint returns the caller's requested page.

Add a concurrency test that creates the required run rows, starts two independent
`engine.begin()` transactions with `ThreadPoolExecutor(max_workers=2)`, inserts the same request
and body under different run IDs, and asserts the two `inserted` results sort to `[False, True]`
with exactly one matching Bronze row.

For atomic rollback, open `with engine.connect() as connection`, begin a transaction, insert RAW,
apply counters and advance checkpoint, then raise a test-only `ForcedRollback`. Roll back and
assert all three changes are absent.

- [x] **Step 2: Run repository tests and verify RED**

Run with `GOVINSIGHT_DATABASE_URL` set:

`.\.venv\Scripts\python.exe -m pytest tests/integration/test_raw_repositories.py -v -p no:cacheprovider`

Expected: collection fails because `govinsight.raw.repositories` does not exist.

- [x] **Step 3: Implement repositories without internal commits**

Use PostgreSQL insert for concurrency-safe idempotency:

```python
statement = (
    postgresql.insert(raw_api_response)
    .values(capture.model_dump())
    .on_conflict_do_nothing(constraint="uq_raw_response_identity_body")
    .returning(raw_api_response.c.id)
)
raw_response_id = connection.execute(statement).scalar_one_or_none()
return InsertOutcome(
    inserted=raw_response_id is not None,
    raw_response_id=raw_response_id,
)
```

`RunRepository.create` inserts a UUID4 `RUNNING` row with zero counters. `apply_page` increments
`pages_processed`, `records_received`, and exactly one of `records_inserted` or
`records_duplicate`. `finish` sets terminal status/time and a nullable safe error code.

`CheckpointRepository.advance` uses PostgreSQL UPSERT keyed by `scope_fingerprint`, stores the
canonical scope and accepts the explicit `completed: bool` derived from page metadata.
`next_page` follows the approved incomplete/completed behavior.

- [x] **Step 4: Verify repositories GREEN**

Run the repository integration test command again.

Expected: idempotency, versioning, exact text, counters, resume and rollback tests pass.

- [x] **Step 5: Commit Task 4**

```powershell
git add src/govinsight/raw/repositories.py tests/integration/test_raw_repositories.py
git commit -m "feat: add transactional raw repositories"
```

---

### Task 5: Resumable paginated ingestion service

**Files:**
- Create: `src/govinsight/raw/service.py`
- Create: `tests/integration/test_raw_service.py`

**Interfaces:**
- Consumes: SQLAlchemy `Engine`, `PNCPClient.fetch_procurements/fetch_contracts`, repositories,
  hashing functions and typed Phase 2 queries.
- Produces: `RawIngestionService.ingest_procurements(query) -> IngestionResult` and
  `RawIngestionService.ingest_contracts(query) -> IngestionResult`.

- [x] **Step 1: Write failing end-to-end service tests**

Use a small fake at the external HTTP boundary that returns real `FetchedPNCPPage` instances for
two pages. Keep repositories and PostgreSQL real. The first ingestion must assert:

```python
assert result.status is RunStatus.SUCCEEDED
assert result.pages_processed == 2
assert result.records_received == 3
assert result.records_inserted == 3
assert result.records_duplicate == 0
```

Replay the completed query using the same bodies and assert the Bronze count stays at two response
rows, a second `etl_run` exists, and its counters report three duplicate records.

Add an interrupted-run test whose fake raises `PNCPRetryExhausted` on page 2. Assert the first run
is `FAILED`, page 1 remains committed and the checkpoint is incomplete at page 1. A second call
must request page 2 first, finish the checkpoint and avoid fetching page 1 again.

Add a contract test proving `ingest_contracts` uses `fetch_contracts`. Assert
`control.etl_watermark` stays empty for every test. Clean test rows by unique `pipeline_name` and
scope fingerprint in `finally` blocks.

- [x] **Step 2: Run service tests and verify RED**

Run with `GOVINSIGHT_DATABASE_URL` set:

`.\.venv\Scripts\python.exe -m pytest tests/integration/test_raw_service.py -v -p no:cacheprovider`

Expected: collection fails because `govinsight.raw.service` does not exist.

- [x] **Step 3: Implement the service and page transaction loop**

Construct `RawIngestionService(engine, client, pipeline_name="pncp_raw")`. Public methods pass a
dataset enum, query and the correct client fetch method to a private typed page loop.

At run start, create the run in `engine.begin()`. Calculate endpoint, full request fingerprint and
scope fingerprint from the actual query parameters. Read the checkpoint and select the starting
page. For every fetched page, build `RawCapture` with:

```python
body_hash = sha256_text(fetched.raw_body)
capture = RawCapture(
    etl_run_id=run_id,
    source="pncp",
    dataset=dataset,
    endpoint=fetched.endpoint,
    request_params=fetched.request_params,
    request_fingerprint=request_fingerprint(
        "pncp", dataset.value, fetched.endpoint, fetched.request_params
    ),
    window_start=query.start_date,
    window_end=query.end_date,
    page_number=fetched.page.page_number,
    http_status=fetched.status_code,
    raw_body=fetched.raw_body,
    body_sha256=body_hash,
    record_count=len(fetched.page.data),
    collected_at=fetched.collected_at,
    duration_ms=fetched.duration_ms,
)
```

Before opening the page transaction, derive `is_final` from empty, zero remaining pages or final
page metadata. Inside one `engine.begin()` block, insert the capture, apply run counters based on
`InsertOutcome.inserted`, and advance the checkpoint with `completed=is_final`. Stop when
`is_final` is true. In a final transaction, mark only the run `SUCCEEDED`; the checkpoint was
already completed atomically with the last RAW page.

Catch project PNCP errors as `PNCP_ERROR`, SQLAlchemy errors as `PERSISTENCE_ERROR`, and other
exceptions as `INGESTION_ERROR`; mark the run `FAILED` in a fresh transaction and re-raise without
including exception text or response content in `error_code`.

- [x] **Step 4: Verify service GREEN**

Run the service integration tests again, followed by:

`.\.venv\Scripts\python.exe -m pytest tests/unit/raw tests/integration/test_raw_repositories.py tests/integration/test_raw_service.py -v -p no:cacheprovider`

Expected: ingestion, replay, interruption, resume, contract and repository tests all pass.

- [x] **Step 5: Commit Task 5**

```powershell
git add src/govinsight/raw/service.py tests/integration/test_raw_service.py
git commit -m "feat: add resumable raw ingestion service"
```

---

### Task 6: Documentation, full gates and Phase 3 checkpoint

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-3.md`
- Modify: `docs/superpowers/plans/2026-08-17-phase-3-raw-layer.md`

**Interfaces:**
- Consumes: fresh measured outputs from every Phase 3 gate.
- Produces: reproducible RAW ingestion instructions and truthful `STAGE_STATUS`.

- [x] **Step 1: Document migration and RAW ingestion usage**

Add a Phase 3 README section showing `alembic upgrade head`, construction of
`RawIngestionService`, one bounded procurement query and the distinction between extraction
checkpoint and untouched end-to-end watermark. Document exact-text storage, uniqueness, retry
inheritance and that no Silver transformation occurs.

- [x] **Step 2: Run the complete local quality suite**

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m pytest -m "not integration" -p no:cacheprovider --cov=govinsight --cov-report=term-missing
```

Expected: zero lint/format failures, all unit tests pass and branch coverage is at least 80%.

- [x] **Step 3: Run real integration and migration gates**

With the Compose database URL set, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_postgres.py tests/integration/test_raw_migration.py tests/integration/test_raw_repositories.py tests/integration/test_raw_service.py -v -p no:cacheprovider
```

Expected: every PostgreSQL test passes; migration restoration leaves revision `20260817_0002`.

- [ ] **Step 4: Run the live API and reproducible stack gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_pncp_live.py -v -p no:cacheprovider
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected: live contract passes, image builds, both containers are healthy and health returns
`ok/reachable`.

- [x] **Step 5: Perform the Phase 3 BUG HUNT**

Inspect edge cases for empty 204 bodies, Unicode hashing, concurrent duplicates, changed bodies,
page-size checkpoint identity, partial failures, run terminal state, rollback, raw-body leakage and
watermark mutation. Inspect API logs for `Traceback`, `ERROR` or `CRITICAL`. Any discovered defect
gets a failing regression test, minimal fix and full relevant retest before continuing.

- [x] **Step 6: Record the checkpoint from fresh evidence**

Create `docs/checkpoints/phase-3.md` using the mandatory checkpoint fields: phase, status, files,
unit/integration test counts, failures, coverage, RAW responses and business records persisted,
duplicates prevented, problems, corrections, risks and Phase 4. Record only measured numbers.

- [ ] **Step 7: Verify repository integrity**

Run:

```powershell
git diff --check
rg --fixed-strings -- "- [ ]" docs/superpowers/plans/2026-08-17-phase-3-raw-layer.md
git status --short
```

Expected: no whitespace errors, no unchecked plan steps after completion, and only intended
documentation changes remain before the final commit.

- [x] **Step 8: Commit documentation and checkpoint**

```powershell
git add README.md docs/checkpoints/phase-3.md docs/superpowers/plans/2026-08-17-phase-3-raw-layer.md
git commit -m "docs: add raw layer guide and checkpoint"
```

- [x] **Step 9: Confirm clean Phase 3 branch**

Run: `git status --short; git log --oneline --decorate -12`

Expected: clean `feat/phase-3-raw-layer` with focused commits and no remote mutation.
