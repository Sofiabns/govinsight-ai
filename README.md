# GovInsight AI

GovInsight AI is an evidence-backed data platform for Brazilian public procurement. It will
ingest official PNCP data, validate and model it for analytics, and expose verified insights
through APIs, dashboards, and guarded AI agents.

## Current status

**Phase 2 — Extraction** adds a validated, paginated and resilient client for the official PNCP
consultation API. The client supports procurement publication/update, contract
publication/update and procurement detail. Persistence remains deliberately deferred to the
Bronze layer in Phase 3.

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

## Project structure

```text
alembic/                  Versioned PostgreSQL migrations
docs/                     Discovery, plans, and phase checkpoints
src/govinsight/api/       FastAPI application
src/govinsight/database/  SQLAlchemy connectivity boundary
src/govinsight/extract/   PNCP query, retry, client, and pagination boundaries
src/govinsight/observability/ Structured logging
tests/unit/               Fast deterministic tests
tests/integration/        Real service contracts
```

## Current limitations

- Phase 2 returns validated records in memory but does not persist RAW payloads.
- Incremental watermarks and idempotent storage begin in Phase 3.
- No analytical tables, dashboard, or AI agents exist yet.
- The Compose defaults are intended only for local development.
