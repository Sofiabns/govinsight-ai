# GovInsight AI

GovInsight AI is an evidence-backed data platform for Brazilian public procurement. It will
ingest official PNCP data, validate and model it for analytics, and expose verified insights
through APIs, dashboards, and guarded AI agents.

It addresses a practical problem: official procurement data is abundant, but extracting a reliable
answer usually requires source integration, data-quality controls and analytical modeling. This
repository packages that path into one reproducible product rather than a collection of notebooks.

## Current status

**Complete release** delivers an idempotent PNCP data pipeline, quality-gated warehouse, analytics
API, responsive dashboard and a six-agent evidence-verification flow.

## Architecture foundation

```text
PNCP -> Bronze RAW -> Silver -> Data quality gate -> Gold star -> Analytics
          |              |             |                  |          |
     exact responses  typed state  score + evidence  dimensions  KPIs + IQR
                         |             |                  |          |
                  safe quarantine  approval watermark  exact money  evidence
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
The dashboard is available at `http://localhost:8000/`.

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

Detailed references: [architecture](docs/architecture.md), [data dictionary](docs/data_dictionary.md),
[agent system](docs/agents.md), and [PNCP source analysis](docs/data_source_analysis.md).

The same lint, formatting, tests and production-image build run automatically in GitHub Actions
for pull requests and pushes to `main`.

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

## Gold data warehouse

After the current Silver snapshot passes the quality gate, load it into Gold in one bounded call:

```python
from govinsight.config import Settings
from govinsight.database.session import create_database_engine
from govinsight.warehouse import WarehouseLoadService

engine = create_database_engine(Settings())
try:
    result = WarehouseLoadService(engine).run_pending()
    print(result.status, result.source_watermark, result.rows_loaded)
finally:
    engine.dispose()
```

`gold.fact_procurement` has one current row per `numero_controle_pncp`. It joins to role-playing
calendar dates plus organization, purchasing unit/location and modality dimensions. Organization,
unit and modality descriptions use Type 1 updates: surrogate keys remain stable while current
descriptions are replaced.

The load proceeds only when the required Silver and Quality watermarks identify the same nonzero
snapshot. A session advisory lock serializes concurrent callers before the `REPEATABLE READ`
transaction begins on the same database connection. Dimension upserts, fact upserts, PK/FK checks, row-count reconciliation,
lineage checks, exact monetary sums and Gold watermark advancement share that transaction. A
mismatch or failed reconciliation rolls everything back; an already loaded snapshot returns a
no-op. Operational logs contain only watermarks, status and aggregate counts, and completion is
emitted only after a successful commit.

Estimated and homologated values remain separate nullable `numeric(19,4)` measures. Homologated
value is not contracted value. A contracted-total metric will be introduced only from a future
contract fact backed by real PNCP contract data.

## Procurement analytics

Use the analytical service after applying Alembic revision `20260830_0006`:

```python
from govinsight.analytics import AnalyticsFilters, AnalyticsService, Measure, RankDimension
from govinsight.config import Settings
from govinsight.database.session import create_database_engine

engine = create_database_engine(Settings())
try:
    analytics = AnalyticsService(engine)
    summary = analytics.summary(AnalyticsFilters(uf="SP"))
    organizations = analytics.rank(RankDimension.ORGANIZATION, limit=10)
    trends = analytics.monthly_trend()
    distribution = analytics.distribution(Measure.HOMOLOGATED)
    outliers = analytics.outliers(Measure.HOMOLOGATED)
finally:
    engine.dispose()
```

The canonical views provide overall, organization, state, modality and publication-month metrics.
Counts include all matching procurements; each monetary average includes only rows where that
measure is present. Shares are null when their denominator is zero. Month-over-month growth is null
when the immediately preceding calendar month is absent or has a zero total.

IQR outliers use exact decimal quartiles and require at least four non-null observations. They are
descriptive evidence of unusual magnitude, not claims of fraud or irregularity. Estimated and
homologated metrics remain explicitly separate; the analytics layer does not expose contracted
value, suppliers, categories or regions because those trusted Gold entities do not exist yet.

## End-to-end pipeline

Run extraction, RAW persistence, Silver transformation, quality validation, Gold loading and the
analytics summary with one command:

```powershell
.\.venv\Scripts\python.exe -m govinsight.orchestration --start 2025-08-01 --end 2025-08-01 --modality 6
```

The command stops immediately if any stage fails or if the quality gate rejects the snapshot. It
prints one JSON result containing the evidence produced by every completed stage.

## Analytics API

With the API running, the interactive documentation at `http://localhost:8000/docs` exposes:

- `GET /analytics/summary`
- `GET /analytics/rankings/{organization|state|modality}`
- `GET /analytics/trends`
- `GET /analytics/distribution`
- `GET /analytics/outliers`

The endpoints accept date, organization, UF and modality filters. Financial measure selections are
restricted to `estimated` and `homologated`; ranking limits are capped at 100.

## Data Analyst Agent

Ask a concise question through `POST /agent/query`:

```json
{"question": "Quais órgãos têm os maiores valores homologados?"}
```

The first agent uses an auditable natural-language baseline and returns only structured metrics,
tables, observations and SQL evidence. Its database boundary accepts a single read-only `SELECT`
against approved Gold analytical views, limits results and applies a five-second timeout. The query
generator is replaceable through a small protocol without coupling the safety gate to an LLM vendor.

`POST /agent/report` runs the full six-agent flow. Statistical, business, data-quality and critic
stages inspect the same evidence before the executive stage is allowed to return a report; no stage
may rewrite computed numbers.

Run the versioned agent benchmark:

```powershell
.\.venv\Scripts\python.exe -m govinsight.agents.evaluation tests/fixtures/agents/agent_evaluation.json
```

It reports intent accuracy, grounded-answer rate and unexpected failure rate, including an
adversarial prompt-injection case.

## Project structure

```text
alembic/                  Versioned PostgreSQL migrations
docs/                     Discovery, plans, and phase checkpoints
src/govinsight/api/       FastAPI application
src/govinsight/api/dashboard/ Responsive analytics dashboard
src/govinsight/database/  SQLAlchemy connectivity boundary
src/govinsight/extract/   PNCP query, retry, client, and pagination boundaries
src/govinsight/raw/       Bronze identities, repositories, and ingestion service
src/govinsight/transform/ Silver typing, quality rules, repositories, and service
src/govinsight/quality/   SQL rules, weighted scoring, evidence, and quality gate
src/govinsight/warehouse/ Gold dimensions, procurement fact, reconciliation, and load service
src/govinsight/analytics/ Typed KPIs, rankings, trends, distributions, and statistical outliers
src/govinsight/agents/    Evidence-backed agents and safe analytical SQL boundary
src/govinsight/observability/ Structured logging
tests/unit/               Fast deterministic tests
tests/integration/        Real service contracts
```

## Current limitations

- Silver currently covers procurement records; contract transformation is intentionally deferred.
- Data-quality rules currently cover only the procurement Silver snapshot.
- Gold currently models procurement only; suppliers, contracts, items, categories and region
  enrichment are intentionally deferred until trusted sources exist.
- Silver and Gold are current-state models; historical SCD Type 2 analysis does not exist yet.
- The natural-language baseline currently recognizes summary, trend and ranking intents; richer
  language-model interpretation is optional and remains behind the generator interface.
- The Compose defaults are intended only for local development.
