# GovInsight AI

GovInsight AI is an evidence-backed data platform for Brazilian public procurement. It will
ingest official PNCP data, validate and model it for analytics, and expose verified insights
through APIs, dashboards, and guarded AI agents.

## Current status

**Phase 5 — Data Quality** audits the procurement Silver snapshot with 12 blocking SQL rules, a
weighted score from 0 to 100 and persisted rule-level evidence. Failed data remains auditable and
cannot advance the quality watermark toward the future Gold warehouse.

## Architecture foundation

```text
PNCP -> Bronze RAW -> Silver transformation -> Data quality gate -> PostgreSQL 16
          |                  |                       |
     exact responses    typed current state     score + evidence
                              |                       |
                       safe quarantine       blocking watermark
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
.\.venv\Scripts\python.exe -m pytest -m integration -p no:cacheprovider -v
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

## Silver transformation

After RAW ingestion, transform at most 100 pending procurement responses in one bounded call:

```python
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.transform import SilverTransformationService

engine = create_database_engine(Settings())
try:
    result = SilverTransformationService(engine).transform_pending(limit=100)
    print(result.model_dump())
finally:
    engine.dispose()
```

Each RAW response is atomic: normalized rows, quarantined records and its watermark commit
together or all roll back. `silver.procurement` keeps the latest valid PNCP version using the
source update timestamp and RAW id as a deterministic tie-breaker. Invalid CNPJ, identifiers,
dates or required fields go to `silver.rejected_record` with reason codes; rejected payloads are
not copied into errors or operational logs.

Re-running with no new RAW data processes zero responses. Newer records update the current state,
older versions never regress it, and a failed response leaves the watermark at the last confirmed
RAW id so a later run can resume safely.

## Data quality gate

After Silver transformation, evaluate the newest procurement snapshot in one bounded call:

```python
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.quality import DataQualityService

engine = create_database_engine(Settings())
try:
    result = DataQualityService(engine).run_pending()
    print(result.model_dump())
finally:
    engine.dispose()
```

The score weights completeness at 30%, validity at 25%, uniqueness at 20%, consistency at 15%
and Bronze lineage integrity at 10%. Each rule persists checked and failed counts in
`control.data_quality_result`; `control.data_quality_run` stores the snapshot score and status.

Any blocking failure keeps the `quality` watermark at the last passing Silver snapshot while
preserving aggregate evidence for investigation. Replaying a previously evaluated snapshot returns
the existing run without duplicating results. After three passing runs, a row-count deviation above
50% becomes a non-blocking `ROW_VOLUME_ANOMALY` warning. Quality evidence never stores PNCP payloads
or free-form source values.

## Project structure

```text
alembic/                  Versioned PostgreSQL migrations
docs/                     Discovery, plans, and phase checkpoints
src/govinsight/api/       FastAPI application
src/govinsight/database/  SQLAlchemy connectivity boundary
src/govinsight/extract/   PNCP query, retry, client, and pagination boundaries
src/govinsight/raw/       Bronze identities, repositories, and ingestion service
src/govinsight/transform/ Silver typing, quality rules, repositories, and service
src/govinsight/quality/   SQL rules, weighted scoring, evidence, and quality gate
src/govinsight/observability/ Structured logging
tests/unit/               Fast deterministic tests
tests/integration/        Real service contracts
```

## Current limitations

- Silver currently covers procurement records; contract transformation is intentionally deferred.
- Data-quality rules currently cover only the procurement Silver snapshot.
- Silver is a current-state operational model, not yet an analytical star schema.
- No analytical tables, dashboard, or AI agents exist yet.
- The Compose defaults are intended only for local development.
