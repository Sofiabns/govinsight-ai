# GovInsight AI

GovInsight AI is an evidence-backed data platform for Brazilian public procurement. It will
ingest official PNCP data, validate and model it for analytics, and expose verified insights
through APIs, dashboards, and guarded AI agents.

## Current status

**Phase 3 — RAW Layer** adds immutable PostgreSQL Bronze storage for exact successful PNCP
responses, auditable ingestion runs and resumable extraction checkpoints. Procurement and
contract collection support publication and update modes while preserving the Phase 2 client
interfaces.

## Architecture foundation

```text
FastAPI -> SQLAlchemy/psycopg -> PostgreSQL 16
             |                     |
        Pydantic Settings      Alembic schemas
             |
       Structlog JSON
```

The initial migration creates the `bronze`, `silver`, `gold`, and `control` schemas. It does
not create procurement tables before their schemas and quality rules are validated in later
phases.

## Requirements

- Python 3.12 for local development
- Docker Engine with Docker Compose for the reproducible stack

## Run with Docker

```powershell
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/health
```

Expected health response:

```json
{
  "status": "ok",
  "database": "reachable"
}
```

The API documentation is available at `http://localhost:8000/docs` while the stack is running.

Stop the services without deleting the database volume:

```powershell
docker compose stop
```

## Local development

Use Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Quality gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -m "not integration" -v --cov=govinsight
```

Live PNCP contract test (requires internet access):

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/integration/test_pncp_live.py -v
```

PostgreSQL integration test, with the Compose stack running:

```powershell
$env:GOVINSIGHT_DATABASE_URL = "postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:5432/govinsight?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/integration/test_postgres.py -v
Remove-Item Env:GOVINSIGHT_DATABASE_URL
```

## Configuration

Settings use the `GOVINSIGHT_` prefix. Copy `.env.example` to `.env` for local overrides; `.env`
is ignored by Git. Docker Compose also supports `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_PORT`, and `API_PORT` substitutions.

Never use the example password outside a local development environment.

## PNCP extraction

The example below requests one bounded page. It does not write data to disk or PostgreSQL:

```python
from datetime import date

from govinsight.config import Settings
from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.models import ProcurementQuery

query = ProcurementQuery(
    start_date=date(2025, 8, 1),
    end_date=date(2025, 8, 1),
    modality_code=6,
    page=1,
    page_size=10,
)

with PNCPClient.from_settings(Settings()) as client:
    page = client.list_procurements(query)

print(page.total_records, len(page.data))
```

Procurement pages accept 10–50 records; contract pages accept 10–500. Dates are emitted as
`YYYYMMDD`, identifiers and ranges are validated before the request, and HTTP 204 becomes an
explicit empty page. Retries are bounded and apply only to transport failures and HTTP 429,
500, 502, 503 and 504. A valid `Retry-After` header takes precedence over exponential backoff.

Operational logs contain only endpoint, status, attempt and duration. Response bodies are not
copied into exceptions or logs. The source fixture under `tests/fixtures/pncp/` preserves a
real response shape, including a nullable homologated value.

## RAW ingestion

Start PostgreSQL and apply the current schema before running a local ingestion:

```powershell
docker compose up -d postgres
$env:GOVINSIGHT_POSTGRES_HOST = "127.0.0.1"
.\.venv\Scripts\alembic.exe upgrade head
```

This bounded example requests procurement publications for one day, starting at page 1 with 10
records per page. The service follows PNCP pagination until the response identifies the final
page:

```python
from datetime import date

from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.models import ProcurementQuery
from govinsight.raw.service import RawIngestionService

settings = Settings()
engine = create_database_engine(settings)

query = ProcurementQuery(
    start_date=date(2025, 8, 1),
    end_date=date(2025, 8, 1),
    modality_code=6,
    page=1,
    page_size=10,
)

try:
    with PNCPClient.from_settings(settings) as client:
        result = RawIngestionService(engine, client).ingest_procurements(query)
    print(result)
finally:
    engine.dispose()
```

Each successful HTTP response is stored as the exact `response.text`; its SHA-256 is calculated
from that text encoded as UTF-8. The full request identity and body hash make identical replays
idempotent, while a changed body creates a new immutable Bronze version. The service inherits the
bounded PNCP retry policy documented above and never stores unsuccessful response bodies.

`control.extraction_checkpoint` records the last successfully committed page for this exact query
scope, including page size, so an interrupted extraction can resume safely. It is separate from
`control.etl_watermark`: Phase 3 creates the end-to-end watermark table but deliberately leaves it
untouched until downstream Silver, Gold and critical quality gates can confirm progress. Phase 3
stores RAW responses only; it performs no Silver transformation or business-record upsert.

## Project structure

```text
alembic/                  Versioned PostgreSQL migrations
docs/                     Discovery, plans, and phase checkpoints
src/govinsight/api/       FastAPI application
src/govinsight/database/  SQLAlchemy connectivity boundary
src/govinsight/extract/   PNCP query, retry, client, and pagination boundaries
src/govinsight/raw/       Bronze identities, repositories, and ingestion service
src/govinsight/observability/ Structured logging
tests/unit/               Fast deterministic tests
tests/integration/        Real service contracts
```

## Current limitations

- Phase 3 persists exact successful responses, not normalized Silver business records.
- The end-to-end watermark remains untouched until downstream stages and quality gates succeed.
- No analytical tables, dashboard, or AI agents exist yet.
- The Compose defaults are intended only for local development.
