# Phase 5 Data Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic PostgreSQL-native quality gate for `silver.procurement` with persisted rule evidence, a weighted 0–100 score and a blocking quality watermark.

**Architecture:** Explicit aggregate SQL rules inspect the current Silver snapshot without loading it into memory. Pure Python scoring converts rule counts into dimension and overall scores; repositories persist immutable run evidence, and one service advances the quality watermark only for a passing snapshot.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, PostgreSQL 16, Alembic, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-5-data-quality-design.md`

## Global Constraints

- Scope is `silver.procurement` only; do not add contracts, items, IBGE, Gold, orchestration, API, dashboard or agents.
- Add no Pandera, Great Expectations or DataFrame dependency.
- Use `Decimal` for every score and persist scores as `numeric(5,2)`.
- Never persist or log RAW bodies, rejected payloads, SQL parameters, credentials or exception chains.
- A blocking data failure is an auditable result, not an exception.
- An infrastructure/query failure raises a safe typed exception after the run receives a safe failure code.
- Advance `control.etl_watermark` stage `quality` only when every blocking rule passes.
- Do not rerun the live PNCP test; Phase 5 consumes local Silver data.
- Use one focused test cycle per task and one complete gate at the end.

---

## File map

| File | Responsibility |
|---|---|
| `src/govinsight/quality/models.py` | Immutable enums and evaluation/run result contracts |
| `src/govinsight/quality/scoring.py` | Rule, dimension and weighted overall score calculation |
| `src/govinsight/quality/rules.py` | Stable PostgreSQL aggregate rule registry |
| `src/govinsight/quality/tables.py` | SQLAlchemy metadata for quality runs and results |
| `src/govinsight/quality/repositories.py` | Run/result/history/watermark persistence |
| `src/govinsight/quality/service.py` | Idempotent quality workflow and transaction boundaries |
| `alembic/versions/20260826_0004_create_data_quality.py` | Reversible control-schema migration |
| `tests/unit/quality/test_scoring.py` | Exact pure scoring behavior |
| `tests/integration/test_quality_migration.py` | Real PostgreSQL schema contract |
| `tests/integration/test_quality_service.py` | Clean, invalid, corrected and replay workflow |
| `README.md` | Bounded execution instructions and semantics |
| `docs/checkpoints/phase-5.md` | Measured gate evidence |

---

### Task 1: Immutable quality contracts and deterministic scoring

**Files:**
- Create: `src/govinsight/quality/__init__.py`
- Create: `src/govinsight/quality/models.py`
- Create: `src/govinsight/quality/scoring.py`
- Create: `tests/unit/quality/test_scoring.py`

**Interfaces:**
- Consumes: no database state.
- Produces: `QualityDimension`, `RuleSeverity`, `RuleStatus`, `QualityRunStatus`, `RuleEvaluation`, `QualityScore`, `DataQualityRunResult`, `calculate_quality_score(evaluations)`.

- [ ] **Step 1: Write the focused failing scoring tests**

Define immutable models and assert exact decimal behavior:

```python
def test_weighted_quality_score_is_exact_and_ignores_warning() -> None:
    evaluations = (
        evaluation("REQUIRED_TEXT_PRESENT", "completeness", 10, 2),
        evaluation("CNPJ_FORMAT_VALID", "validity", 10, 0),
        evaluation("NATURAL_KEY_UNIQUE", "uniqueness", 10, 0),
        evaluation("PROPOSAL_WINDOW_VALID", "consistency", 10, 0),
        evaluation("BRONZE_LINEAGE_VALID", "integrity", 10, 0),
        warning("ROW_VOLUME_ANOMALY", failed_count=1),
    )
    result = calculate_quality_score(evaluations)
    assert result.overall == Decimal("94.00")
    assert result.dimensions[QualityDimension.COMPLETENESS] == Decimal("80.00")
    assert result.blocking_failures == 1


def test_empty_dataset_is_zero_and_not_evaluated_rules_are_excluded() -> None:
    result = calculate_quality_score(
        (
            evaluation("DATASET_NOT_EMPTY", "completeness", 1, 1),
            not_evaluated("UF_DOMAIN_VALID", "validity"),
        )
    )
    assert result.overall == Decimal("0.00")
    assert result.blocking_failures == 1
```

- [ ] **Step 2: Run RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\quality\test_scoring.py -q -p no:cacheprovider --tb=short
```

Expected: collection fails because `govinsight.quality` does not exist.

- [ ] **Step 3: Implement the contracts**

Use string enums and frozen Pydantic models:

```python
class QualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    CONSISTENCY = "consistency"
    INTEGRITY = "integrity"
    VOLUME = "volume"


class RuleSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class RuleStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    NOT_EVALUATED = "not_evaluated"


class QualityRunStatus(StrEnum):
    NOOP = "NOOP"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RuleEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_code: str
    dimension: QualityDimension
    severity: RuleSeverity
    status: RuleStatus
    checked_count: Annotated[int, Field(ge=0)]
    failed_count: Annotated[int, Field(ge=0)]
    score: Annotated[Decimal, Field(ge=0, le=100)] | None
    details: dict[str, int | str | Decimal] = Field(default_factory=dict)
```

`QualityScore` contains `overall: Decimal`, `dimensions: dict[QualityDimension, Decimal]` and
`blocking_failures: int`. `DataQualityRunResult` is frozen and contains `run_id: int | None`,
`source_watermark: int`, `status: QualityRunStatus`, `rows_evaluated: int`,
`score: Decimal | None`, `blocking_failures: int`, `evaluations: tuple[RuleEvaluation, ...]` and
`reused: bool`.

- [ ] **Step 4: Implement exact scoring**

Use these fixed weights:

```python
DIMENSION_WEIGHTS = {
    QualityDimension.COMPLETENESS: Decimal("0.30"),
    QualityDimension.VALIDITY: Decimal("0.25"),
    QualityDimension.UNIQUENESS: Decimal("0.20"),
    QualityDimension.CONSISTENCY: Decimal("0.15"),
    QualityDimension.INTEGRITY: Decimal("0.10"),
}
SCORE_QUANTUM = Decimal("0.01")
```

Calculate each evaluated rule as `(checked - failed) * 100 / checked`, clamp to `[0, 100]`,
average evaluated rules within the dimension and apply the fixed weights. `VOLUME` never enters the
weighted score. When `DATASET_NOT_EMPTY` fails, return overall `0.00`. Count failed blocking rules,
not failed rows.

- [ ] **Step 5: Run GREEN and quality checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\quality\test_scoring.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\quality tests\unit\quality
.\.venv\Scripts\ruff.exe format --check src\govinsight\quality tests\unit\quality
```

Expected: focused tests and both Ruff checks pass.

- [ ] **Step 6: Commit**

```powershell
git add src/govinsight/quality tests/unit/quality/test_scoring.py
git commit -m "feat: add deterministic data quality scoring"
```

---

### Task 2: Quality audit schema and reversible migration

**Files:**
- Create: `src/govinsight/quality/tables.py`
- Create: `alembic/versions/20260826_0004_create_data_quality.py`
- Create: `tests/integration/test_quality_migration.py`

**Interfaces:**
- Consumes: shared metadata from `govinsight.raw.tables.metadata` and Alembic head `20260823_0003`.
- Produces: `data_quality_run` and `data_quality_result` SQLAlchemy tables in schema `control`.

- [ ] **Step 1: Write the migration contract first**

The integration test downgrades to `20260823_0003`, upgrades to head and inspects:

```python
assert {"data_quality_run", "data_quality_result"} <= set(
    inspector.get_table_names(schema="control")
)
assert {column["name"] for column in inspector.get_columns("data_quality_run", schema="control")} >= {
    "id", "dataset", "stage", "source_watermark", "status", "started_at", "finished_at",
    "rows_evaluated", "score", "blocking_failures", "error_code",
}
assert any(
    set(item["column_names"]) == {"dataset", "source_watermark"}
    for item in inspector.get_unique_constraints("data_quality_run", schema="control")
)
```

Also assert the result foreign key targets `control.data_quality_run.id`, uniqueness on
`(run_id, rule_code)`, named score/count/status checks, then downgrade and restore head in `finally`.

- [ ] **Step 2: Run RED**

```powershell
$env:GOVINSIGHT_DATABASE_URL = "postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:54320/govinsight?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest tests\integration\test_quality_migration.py -q -p no:cacheprovider --tb=short
```

Expected: fail because the quality tables and revision do not exist.

- [ ] **Step 3: Implement table metadata**

`data_quality_run` uses identity `BigInteger` primary key, text dataset/stage/status, `BigInteger`
source watermark, timezone-aware timestamps, integer counts and `Numeric(5, 2)` score. Add:

```python
sa.UniqueConstraint("dataset", "source_watermark", name="uq_quality_run_snapshot")
sa.CheckConstraint("status IN ('RUNNING', 'PASSED', 'FAILED')", name="ck_quality_run_status")
sa.CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_quality_run_score")
sa.CheckConstraint("rows_evaluated >= 0 AND blocking_failures >= 0", name="ck_quality_run_counts")
```

`data_quality_result` uses a cascading run foreign key, rule metadata, counts, optional score,
JSONB details and evaluation timestamp. Add status, score, non-negative-count and
`failed_count <= checked_count` checks plus uniqueness on `(run_id, rule_code)`.

- [ ] **Step 4: Implement Alembic revision `20260826_0004`**

Set `down_revision = "20260823_0003"`. Create `data_quality_run` before
`data_quality_result`; create indexes for run status/time and result rule/status. Downgrade drops the
result table before the run table. Use the same types, names and constraints as metadata.

- [ ] **Step 5: Run GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_quality_migration.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\quality\tables.py alembic\versions\20260826_0004_create_data_quality.py tests\integration\test_quality_migration.py
```

Expected: migration contract passes against real PostgreSQL and head is restored.

- [ ] **Step 6: Commit**

```powershell
git add src/govinsight/quality/tables.py alembic/versions/20260826_0004_create_data_quality.py tests/integration/test_quality_migration.py
git commit -m "feat: create data quality audit schema"
```

---

### Task 3: SQL rules, persistence and blocking quality service

**Files:**
- Create: `src/govinsight/quality/rules.py`
- Create: `src/govinsight/quality/repositories.py`
- Create: `src/govinsight/quality/service.py`
- Modify: `src/govinsight/quality/__init__.py`
- Create: `tests/integration/test_quality_service.py`

**Interfaces:**
- Consumes: `silver.procurement`, Bronze RAW lineage, Silver watermark and Task 1/2 contracts.
- Produces: `DataQualityService(engine).run_pending() -> DataQualityRunResult`.

- [ ] **Step 1: Write one end-to-end failing integration test**

Use real PostgreSQL and isolated natural keys. The test must:

1. seed one valid Silver procurement and Silver watermark;
2. run quality and assert `PASSED`, score `100.00`, twelve blocking rules persisted and quality
   watermark advanced;
3. assert replay returns the existing run without duplicate results;
4. add a newer RAW/Silver snapshot containing one direct SQL row with blank `objeto_compra` and
   `uf_sigla='ZZ'`;
5. assert `REQUIRED_TEXT_PRESENT` and `UF_DOMAIN_VALID` fail, status is `FAILED`, safe aggregate
   details omit the injected object text, and quality watermark remains at the first snapshot;
6. add a corrected newer Silver snapshot and assert `PASSED` with quality watermark advancement;
7. create three prior passing counts, then verify a greater-than-50% row-count deviation produces
   `ROW_VOLUME_ANOMALY` warning without failing the run;
8. clean only rows and runs created by the test.

The first RED failure must be an import error for `govinsight.quality.service`.

- [ ] **Step 2: Implement the explicit rule registry**

Define:

```python
@dataclass(frozen=True)
class RuleDefinition:
    code: str
    dimension: QualityDimension
    severity: RuleSeverity
    statement: sa.Select
```

Every statement returns exactly `checked_count` and `failed_count`. Use aggregate predicates:

- required text: `trim(column) = ''` across PNCP key, organization/unit/modality names and object;
- required dates: null publication/global-update timestamps;
- CNPJ/IBGE regex and official UF allowlist;
- non-negative money with the schema maximum;
- grouped duplicate subqueries for natural key and source position;
- proposal window comparison and PNCP-key year comparison;
- outer join to `bronze.raw_api_response` for missing lineage.

Keep stable rule order matching the specification. Do not interpolate data values into SQL strings.

- [ ] **Step 3: Implement repositories**

Provide these exact operations:

- `QualityWatermarkRepository.silver_current(connection: Connection) -> int`
- `QualityWatermarkRepository.quality_current(connection: Connection, *, lock: bool = False) -> int`
- `QualityWatermarkRepository.advance(connection: Connection, raw_response_id: int) -> None`
- `QualityRunRepository.start_or_get(connection: Connection, source_watermark: int) -> QualityRunState`
- `QualityRunRepository.complete(connection: Connection, run_id: int, result: DataQualityRunResult) -> None`
- `QualityRunRepository.fail_execution(connection: Connection, run_id: int, error_code: str) -> None`
- `QualityRunRepository.successful_row_counts(connection: Connection, limit: int = 10) -> tuple[int, ...]`
- `QualityResultRepository.replace(connection: Connection, run_id: int, values: tuple[RuleEvaluation, ...]) -> None`

`QualityRunState` is a frozen internal dataclass with `run_id: int`,
`status: QualityRunStatus` and `created: bool`. `created=False` tells the service to load and return
the existing completed evidence without executing rules again.

Use PostgreSQL `ON CONFLICT` for snapshot idempotency and monotonic watermark advancement. Existing
completed snapshots are returned unchanged. Persist only aggregate `details`.

- [ ] **Step 4: Implement the service transaction flow**

`DataQualityService.run_pending()` reads Silver and quality watermarks. If Silver is zero or not
newer, return a frozen no-op result. Otherwise create/recover the run, execute all rules in one
read-consistent transaction, append the volume evaluation, calculate the score, persist results and
finalize status. Advance quality watermark only on `PASSED`.

Use stable safe errors:

```python
class DataQualityExecutionError(RuntimeError):
    def __init__(self, run_id: int, code: str) -> None:
        self.run_id = run_id
        self.code = code
        super().__init__(f"Data quality execution failed with {code} for run {run_id}")
```

Translate SQLAlchemy failures to `QUALITY_QUERY_FAILED` without retaining the original exception as
implicit context. Record the safe code in a separate transaction, then raise with `from None`.

- [ ] **Step 5: Run GREEN and scoped quality checks**

```powershell
$env:GOVINSIGHT_DATABASE_URL = "postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:54320/govinsight?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest tests\unit\quality\test_scoring.py tests\integration\test_quality_migration.py tests\integration\test_quality_service.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\quality tests\unit\quality tests\integration\test_quality_migration.py tests\integration\test_quality_service.py
```

Expected: scoring, migration and service tests pass with real PostgreSQL; lint is clean.

- [ ] **Step 6: Commit**

```powershell
git add src/govinsight/quality tests/integration/test_quality_service.py
git commit -m "feat: add blocking data quality gate"
```

---

### Task 4: Documentation, measured checkpoint and Phase 5 gate

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-5.md`
- Modify: `docs/superpowers/plans/2026-08-26-phase-5-data-quality.md`

**Interfaces:**
- Consumes: fresh output from every Phase 5 gate.
- Produces: reproducible quality execution and truthful `STAGE_STATUS`.

- [ ] **Step 1: Document one bounded execution**

Add a README example:

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

Explain score weights, blocking rules, persisted evidence, replay semantics, quality watermark and
the procurement-only boundary.

- [ ] **Step 2: Run final gates once**

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
$env:GOVINSIGHT_DATABASE_URL = "postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:54320/govinsight?connect_timeout=5"
.\.venv\Scripts\python.exe -m pytest -m "not live_api" -p no:cacheprovider --cov=govinsight --cov-report=term-missing -q
$env:GOVINSIGHT_POSTGRES_HOST = "127.0.0.1"
$env:GOVINSIGHT_POSTGRES_PORT = "54320"
.\.venv\Scripts\python.exe -m alembic current
```

Expected: lint/format clean, all local/PostgreSQL tests pass, coverage is at least 80%, one live test
is deselected and Alembic reports `20260826_0004 (head)`.

- [ ] **Step 3: Perform the compact BUG HUNT**

Inspect only: empty dataset, blank text, invalid UF, duplicate evidence, failed watermark, replay,
score rounding, volume baseline, SQL failure sanitization and concurrent snapshot start. Add one
focused regression only for a real defect.

- [ ] **Step 4: Write measured checkpoint and close the plan**

Record exact files, test counts, coverage, rows checked, rule pass/fail/warning counts, score,
problems, corrections, risks and Phase 6. Mark every checkbox only after evidence exists.

- [ ] **Step 5: Verify and commit**

```powershell
git diff --check
rg -n "^- \[ \]" docs/superpowers/plans/2026-08-26-phase-5-data-quality.md
git status --short
git add README.md docs/checkpoints/phase-5.md docs/superpowers/plans/2026-08-26-phase-5-data-quality.md
git commit -m "docs: add data quality guide and checkpoint"
```
