# Phase 6 Data Warehouse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an idempotent Gold procurement star schema that loads only the current quality-approved Silver snapshot and proves exact structural and financial reconciliation.

**Architecture:** A focused `govinsight.warehouse` package owns Gold metadata, typed results, set-based repositories, and a `REPEATABLE READ` orchestration service. The service requires equal Silver and Quality watermarks, upserts Type 1 dimensions and one fact per PNCP control key, validates the completed star, and advances the Gold watermark in the same transaction.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, PostgreSQL 16, Alembic, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-26-phase-6-data-warehouse-design.md`

## Global Constraints

- Model only the procurement grain present in `silver.procurement`.
- Do not create contracts, suppliers, items, results, categories, regions, SCD Type 2 history, or a contracted-value measure.
- Keep `valor_total_estimado` and `valor_total_homologado` as nullable `numeric(19,4)` values; never convert them to float or zero-fill nulls.
- Use Type 1 updates for organization, unit, and modality dimensions.
- Load only when `silver_watermark == quality_watermark > gold_watermark`; return no-op only when all three are equal.
- Use one `REPEATABLE READ` transaction for dimension/fact writes, reconciliation, and watermark advancement.
- Do not delete Gold facts without an authoritative upstream deletion signal.
- Do not rerun the live PNCP test; use one focused cycle per task and one complete regression gate at the end.

---

## File map

| File | Responsibility |
|---|---|
| `alembic/versions/20260826_0005_create_gold_warehouse.py` | Reversible Gold star-schema migration |
| `src/govinsight/warehouse/tables.py` | SQLAlchemy metadata for four dimensions and one fact |
| `src/govinsight/warehouse/models.py` | Immutable load status, result, reconciliation, and error contracts |
| `src/govinsight/warehouse/repositories.py` | Watermark state, set-based upserts, and reconciliation queries |
| `src/govinsight/warehouse/service.py` | Transaction and quality-gate orchestration |
| `src/govinsight/warehouse/__init__.py` | Stable public exports |
| `tests/integration/test_warehouse_migration.py` | PostgreSQL schema, constraint, index, upgrade, and downgrade contract |
| `tests/integration/test_warehouse_service.py` | Approved load, joins, money, replay, update, blocking, and rollback behavior |
| `README.md` | Gold usage and financial semantics |
| `docs/checkpoints/phase-6.md` | Final verification evidence |

---

### Task 1: Gold star-schema metadata and reversible migration

**Files:**
- Create: `src/govinsight/warehouse/tables.py`
- Create: `alembic/versions/20260826_0005_create_gold_warehouse.py`
- Create: `tests/integration/test_warehouse_migration.py`

**Interfaces:**
- Consumes: shared `metadata` from `govinsight.raw.tables` and Alembic head `20260826_0004`.
- Produces: `dim_date`, `dim_organization`, `dim_unit`, `dim_modality`, and `fact_procurement` SQLAlchemy tables in schema `gold`.

- [x] **Step 1: Write the failing migration contract**

Create an integration test that downgrades to `20260826_0004`, upgrades to `head`, and asserts the exact table set:

```python
expected = {
    "dim_date",
    "dim_organization",
    "dim_unit",
    "dim_modality",
    "fact_procurement",
}
assert expected <= set(inspector.get_table_names(schema="gold"))
assert inspector.get_pk_constraint("fact_procurement", schema="gold")["constrained_columns"] == [
    "procurement_key"
]
assert {item["name"] for item in inspector.get_unique_constraints(
    "fact_procurement", schema="gold"
)} >= {"uq_gold_fact_procurement_pncp"}
assert {item["name"] for item in inspector.get_foreign_keys(
    "fact_procurement", schema="gold"
)} >= {
    "fk_gold_fact_organization",
    "fk_gold_fact_unit",
    "fk_gold_fact_modality",
    "fk_gold_fact_publication_date",
    "fk_gold_fact_opening_date",
    "fk_gold_fact_closing_date",
    "fk_gold_fact_raw",
}
```

Also assert natural-key uniqueness for every dimension, `numeric(19,4)` for both monetary columns, the expected indexes, downgrade removal, and restoration to `head` in `finally`.

- [x] **Step 2: Run RED**

```powershell
$env:GOVINSIGHT_DATABASE_URL='postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:54320/govinsight?connect_timeout=5'
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_migration.py -q -p no:cacheprovider --tb=short
```

Expected: FAIL because revision `20260826_0005` and the Gold tables do not exist.

- [x] **Step 3: Define the SQLAlchemy tables**

Use the shared metadata and these stable identifiers:

```python
dim_date = sa.Table(
    "dim_date", metadata,
    sa.Column("date_key", sa.Integer(), primary_key=True),
    sa.Column("full_date", sa.Date(), nullable=False, unique=True),
    sa.Column("day", sa.SmallInteger(), nullable=False),
    sa.Column("month", sa.SmallInteger(), nullable=False),
    sa.Column("quarter", sa.SmallInteger(), nullable=False),
    sa.Column("year", sa.SmallInteger(), nullable=False),
    sa.Column("iso_weekday", sa.SmallInteger(), nullable=False),
    schema="gold",
)

dim_organization = sa.Table(
    "dim_organization", metadata,
    sa.Column("organization_key", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("orgao_cnpj", sa.CHAR(14), nullable=False, unique=True),
    sa.Column("orgao_razao_social", sa.Text(), nullable=False),
    sa.Column("poder_id", sa.Text()),
    sa.Column("esfera_id", sa.Text()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    schema="gold",
)
```

Define `dim_unit` with surrogate `unit_key`, unique `(orgao_cnpj, codigo_unidade)`, name and location attributes; `dim_modality` with surrogate `modality_key` and unique `modalidade_id`; and `fact_procurement` with:

```python
sa.Column("procurement_key", sa.BigInteger(), sa.Identity(), primary_key=True)
sa.Column("numero_controle_pncp", sa.Text(), nullable=False, unique=True)
sa.Column("organization_key", sa.BigInteger(), nullable=False)
sa.Column("unit_key", sa.BigInteger(), nullable=False)
sa.Column("modality_key", sa.BigInteger(), nullable=False)
sa.Column("publication_date_key", sa.Integer(), nullable=False)
sa.Column("opening_date_key", sa.Integer())
sa.Column("closing_date_key", sa.Integer())
sa.Column("source_raw_response_id", sa.BigInteger(), nullable=False)
sa.Column("normalized_sha256", sa.CHAR(64), nullable=False)
sa.Column("ano_compra", sa.Integer(), nullable=False)
sa.Column("sequencial_compra", sa.Integer(), nullable=False)
sa.Column("numero_compra", sa.Text())
sa.Column("srp", sa.Boolean(), nullable=False)
sa.Column("objeto_compra", sa.Text(), nullable=False)
sa.Column("situacao_compra_id", sa.Integer())
sa.Column("situacao_compra_nome", sa.Text())
sa.Column("tipo_instrumento_codigo", sa.Integer())
sa.Column("tipo_instrumento_nome", sa.Text())
sa.Column("valor_total_estimado", sa.Numeric(19, 4))
sa.Column("valor_total_homologado", sa.Numeric(19, 4))
sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)
sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)
```

Add named FKs to all dimensions and `bronze.raw_api_response.id`, nonnegative monetary checks, natural-key checks, and indexes for organization, unit, modality, publication date, and procurement year.

- [x] **Step 4: Create Alembic revision `20260826_0005`**

Set:

```python
revision = "20260826_0005"
down_revision = "20260826_0004"
```

Create dimensions before the fact in `upgrade()`. Drop the fact before dimensions in `downgrade()`. Mirror every table, constraint, and index name from `tables.py`.

- [x] **Step 5: Run GREEN and schema lint**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_migration.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\warehouse\tables.py alembic\versions\20260826_0005_create_gold_warehouse.py tests\integration\test_warehouse_migration.py
```

Expected: migration test and Ruff pass; database returns to Alembic head.

- [x] **Step 6: Commit**

```powershell
git add src/govinsight/warehouse/tables.py alembic/versions/20260826_0005_create_gold_warehouse.py tests/integration/test_warehouse_migration.py
git commit -m "feat: create gold procurement star schema"
```

---

### Task 2: Typed load state and set-based warehouse repositories

**Files:**
- Create: `src/govinsight/warehouse/__init__.py`
- Create: `src/govinsight/warehouse/models.py`
- Create: `src/govinsight/warehouse/repositories.py`
- Create: `tests/integration/test_warehouse_service.py`

**Interfaces:**
- Consumes: Gold tables from Task 1, `silver.procurement`, and `control.etl_watermark`.
- Produces: `WarehouseLoadStatus`, `WarehouseLoadResult`, `ReconciliationResult`, `WarehouseStateError`, `WarehouseWatermarkRepository`, and `WarehouseRepository`.

- [x] **Step 1: Write the failing repository-level integration scenario**

Seed two valid Silver rows and equal Silver/Quality watermarks, call repository methods in one transaction, and assert:

```python
assert counts == {
    "dates": 5,
    "organizations": 2,
    "units": 2,
    "modalities": 1,
    "facts": 2,
}
assert reconciliation == ReconciliationResult(
    silver_rows=2,
    fact_rows=2,
    missing_in_fact=0,
    missing_in_silver=0,
    orphan_foreign_keys=0,
    lineage_mismatches=0,
    estimated_silver=Decimal("350.2500"),
    estimated_fact=Decimal("350.2500"),
    estimated_nulls_silver=0,
    estimated_nulls_fact=0,
    homologated_silver=Decimal("300.0000"),
    homologated_fact=Decimal("300.0000"),
    homologated_nulls_silver=1,
    homologated_nulls_fact=1,
)
assert reconciliation.is_valid is True
```

Query joined facts to prove every dimension key resolves and date roles point to the correct calendar rows.

- [x] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_service.py::test_repository_builds_reconciled_star -q -p no:cacheprovider --tb=short
```

Expected: FAIL because `govinsight.warehouse.models` and repository classes do not exist.

- [x] **Step 3: Implement immutable contracts**

```python
class WarehouseLoadStatus(StrEnum):
    NOOP = "NOOP"
    LOADED = "LOADED"


class WarehouseLoadResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: WarehouseLoadStatus
    source_watermark: Annotated[int, Field(ge=0)]
    rows_loaded: Annotated[int, Field(ge=0)]
    reused: bool = False


class WarehouseWatermarkState(BaseModel):
    model_config = ConfigDict(frozen=True)
    silver: Annotated[int, Field(ge=0)]
    quality: Annotated[int, Field(ge=0)]
    gold: Annotated[int, Field(ge=0)]


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    silver_rows: Annotated[int, Field(ge=0)]
    fact_rows: Annotated[int, Field(ge=0)]
    missing_in_fact: Annotated[int, Field(ge=0)]
    missing_in_silver: Annotated[int, Field(ge=0)]
    orphan_foreign_keys: Annotated[int, Field(ge=0)]
    lineage_mismatches: Annotated[int, Field(ge=0)]
    estimated_silver: Decimal
    estimated_fact: Decimal
    estimated_nulls_silver: Annotated[int, Field(ge=0)]
    estimated_nulls_fact: Annotated[int, Field(ge=0)]
    homologated_silver: Decimal
    homologated_fact: Decimal
    homologated_nulls_silver: Annotated[int, Field(ge=0)]
    homologated_nulls_fact: Annotated[int, Field(ge=0)]

    @property
    def is_valid(self) -> bool:
        return (
            self.silver_rows == self.fact_rows
            and self.missing_in_fact == self.missing_in_silver == 0
            and self.orphan_foreign_keys == self.lineage_mismatches == 0
            and self.estimated_silver == self.estimated_fact
            and self.estimated_nulls_silver == self.estimated_nulls_fact
            and self.homologated_silver == self.homologated_fact
            and self.homologated_nulls_silver == self.homologated_nulls_fact
        )
```

`WarehouseStateError(code: str)` stores a safe `code` and uses it as its exception message. Export all four contracts from `warehouse/__init__.py`.

- [x] **Step 4: Implement strict watermark state**

Use constants:

```python
DATASET = "procurements"
SILVER_PIPELINE = "silver_procurement"
QUALITY_PIPELINE = "data_quality"
WAREHOUSE_PIPELINE = "gold_procurement"
```

`WarehouseWatermarkRepository.read_state(connection, lock_gold=True)` must parse nonnegative integer `last_raw_response_id` values for Silver, Quality, and Gold, returning a frozen `WarehouseWatermarkState`. Missing rows mean zero; malformed JSON or negative values raise `WarehouseStateError("INVALID_WATERMARK")`. `advance(connection, raw_response_id)` performs a monotonic PostgreSQL upsert for the Gold key.

- [x] **Step 5: Implement set-based Type 1 upserts**

`WarehouseRepository.load_dimensions(connection: Connection) -> dict[str, int]` builds a concrete distinct SQLAlchemy select from `silver.procurement`, passes it to `postgresql.insert(target).from_select(target_columns, source_select)`, and applies `on_conflict_do_update` for organization, unit, and modality. It returns current total counts under keys `dates`, `organizations`, `units`, and `modalities`. Insert the union of distinct non-null calendar dates from publication/opening/closing timestamps into `dim_date` with deterministic:

```python
date_key = year * 10000 + month * 100 + day
quarter = extract("quarter", source_date)
iso_weekday = extract("isodow", source_date)
```

Dimension conflict updates replace only current descriptive attributes and `updated_at`; primary/natural keys and `created_at` stay stable.

- [x] **Step 6: Implement fact upsert and reconciliation**

`WarehouseRepository.load_facts(connection: Connection) -> int` joins Silver to dimensions by natural keys and upserts by `numero_controle_pncp`. Update every mutable fact attribute, FK, lineage field, monetary measure, and `updated_at`; preserve `procurement_key` and `created_at`. Return the total fact count after the upsert so `rows_loaded` describes the reconciled snapshot rather than PostgreSQL's inserted/updated command count.

`WarehouseRepository.reconcile(connection: Connection) -> ReconciliationResult` uses SQL aggregates and anti-joins. Apply `coalesce(sum(value), numeric '0')` only to aggregate comparison fields while separately comparing null counts. Do not alter stored fact values.

- [x] **Step 7: Run GREEN and repository lint**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_service.py::test_repository_builds_reconciled_star -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\warehouse tests\integration\test_warehouse_service.py
```

Expected: focused scenario and Ruff pass.

- [x] **Step 8: Commit**

```powershell
git add src/govinsight/warehouse tests/integration/test_warehouse_service.py
git commit -m "feat: add gold warehouse repositories"
```

---

### Task 3: Transactional quality-gated warehouse service

**Files:**
- Create: `src/govinsight/warehouse/service.py`
- Modify: `src/govinsight/warehouse/__init__.py`
- Modify: `tests/integration/test_warehouse_service.py`

**Interfaces:**
- Consumes: `WarehouseWatermarkRepository`, `WarehouseRepository`, `WarehouseLoadResult`, and `WarehouseStateError` from Task 2.
- Produces: `WarehouseLoadService(engine: Engine).run_pending() -> WarehouseLoadResult`.

- [x] **Step 1: Write focused failing workflow tests**

Cover four behaviors in the existing integration file:

```python
def seed_watermarks(engine: Engine, *, silver: int, quality: int, gold: int) -> None:
    """Replace only the three procurement watermark rows used by the test."""


def seed_approved_silver(engine: Engine, records: list[dict[str, object]]) -> int:
    """Insert Bronze lineage + Silver rows and set equal Silver/Quality watermarks."""


def gold_counts(engine: Engine) -> tuple[int, int, int, int, int]:
    """Return dimension and fact counts in stable table order."""


def gold_watermark(engine: Engine) -> int:
    """Read the Gold last_raw_response_id or return zero when absent."""


def test_approved_snapshot_loads_and_exact_replay_is_noop(engine: Engine) -> None:
    watermark = seed_approved_silver(engine, two_procurements())
    first = WarehouseLoadService(engine).run_pending()
    second = WarehouseLoadService(engine).run_pending()
    assert first == WarehouseLoadResult(
        status=WarehouseLoadStatus.LOADED,
        source_watermark=watermark,
        rows_loaded=2,
        reused=False,
    )
    assert second.status is WarehouseLoadStatus.NOOP
    assert second.source_watermark == watermark
    assert second.reused is True


def test_silver_quality_mismatch_blocks_without_gold_writes(engine: Engine) -> None:
    seed_watermarks(engine, silver=20, quality=19, gold=0)
    with pytest.raises(WarehouseStateError, match="UNAPPROVED_SILVER_SNAPSHOT"):
        WarehouseLoadService(engine).run_pending()
    assert gold_counts(engine) == (0, 0, 0, 0, 0)
    assert gold_watermark(engine) == 0


def test_later_snapshot_updates_type_one_dimensions_and_fact(engine: Engine) -> None:
    first_watermark = seed_approved_silver(engine, [procurement_record(value="100.0000")])
    WarehouseLoadService(engine).run_pending()
    before = read_dimension_and_fact_identity(engine)

    second_watermark = update_approved_silver(
        engine,
        procurement_record(
            organization_name="Órgão Atualizado",
            unit_name="Unidade Atualizada",
            modality_name="Modalidade Atualizada",
            value="125.5000",
        ),
    )
    result = WarehouseLoadService(engine).run_pending()
    after = read_dimension_and_fact_identity(engine)

    assert second_watermark > first_watermark
    assert result.source_watermark == second_watermark
    assert after.organization_key == before.organization_key
    assert after.unit_key == before.unit_key
    assert after.modality_key == before.modality_key
    assert after.procurement_key == before.procurement_key
    assert after.organization_name == "Órgão Atualizado"
    assert after.unit_name == "Unidade Atualizada"
    assert after.modality_name == "Modalidade Atualizada"
    assert after.estimated_value == Decimal("125.5000")
    assert after.normalized_sha256 != before.normalized_sha256
    assert after.source_raw_response_id > before.source_raw_response_id
    assert after.created_at == before.created_at
    assert after.updated_at >= before.updated_at


def test_reconciliation_failure_rolls_back_all_gold_changes(engine: Engine, monkeypatch) -> None:
    monkeypatch.setattr(WarehouseRepository, "reconcile", invalid_reconciliation)
    with pytest.raises(WarehouseStateError, match="RECONCILIATION_FAILED"):
        WarehouseLoadService(engine).run_pending()
    assert gold_counts(engine) == (0, 0, 0, 0, 0)
    assert gold_watermark(engine) == 0
```

Use real PostgreSQL state for every assertion. The monkeypatch changes only the returned reconciliation result so transaction rollback remains real.
Implement the named helpers locally in the test module: use unique PNCP keys/CNPJs per test, insert matching `bronze.raw_api_response` lineage before Silver rows, and delete only those unique rows plus the three warehouse watermark keys during cleanup. `procurement_record`, `update_approved_silver`, and `read_dimension_and_fact_identity` must return concrete fixture data/a frozen identity record; they are test utilities, not production interfaces.

- [x] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_service.py -q -p no:cacheprovider --tb=short
```

Expected: repository scenario passes; service scenarios fail because `WarehouseLoadService` does not exist.

- [x] **Step 3: Implement state validation**

Use this decision table before any Gold write:

```python
if state.silver == 0 and state.quality == 0 and state.gold == 0:
    return noop(0)
if state.silver != state.quality:
    raise WarehouseStateError("UNAPPROVED_SILVER_SNAPSHOT")
if state.gold > state.quality:
    raise WarehouseStateError("GOLD_WATERMARK_AHEAD")
if state.gold == state.quality:
    return noop(state.gold)
```

This makes missing Quality approval, failed newer Quality snapshots, and contradictory progress explicit.

- [x] **Step 4: Implement the transaction**

```python
class WarehouseLoadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._watermarks = WarehouseWatermarkRepository()
        self._warehouse = WarehouseRepository()

    def run_pending(self) -> WarehouseLoadResult:
        with self._engine.connect() as connection:
            connection = connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                state = self._watermarks.read_state(connection, lock_gold=True)
                early_result = self._validate_state(state)
                if early_result is not None:
                    return early_result
                self._warehouse.load_dimensions(connection)
                rows_loaded = self._warehouse.load_facts(connection)
                reconciliation = self._warehouse.reconcile(connection)
                if not reconciliation.is_valid:
                    raise WarehouseStateError("RECONCILIATION_FAILED")
                self._watermarks.advance(connection, state.silver)
                return WarehouseLoadResult(
                    status=WarehouseLoadStatus.LOADED,
                    source_watermark=state.silver,
                    rows_loaded=rows_loaded,
                )
```

Export the service and public models from `warehouse/__init__.py`. Do not catch SQLAlchemy errors merely to rename them; allowing them out of the transaction guarantees rollback and preserves actionable infrastructure diagnostics.

- [x] **Step 5: Run GREEN and focused quality checks**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_service.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\warehouse tests\integration\test_warehouse_service.py
.\.venv\Scripts\ruff.exe format --check src\govinsight\warehouse tests\integration\test_warehouse_service.py
```

Expected: all warehouse workflow tests and Ruff checks pass.

- [x] **Step 6: Commit**

```powershell
git add src/govinsight/warehouse tests/integration/test_warehouse_service.py
git commit -m "feat: add quality-gated gold load"
```

---

### Task 4: Portfolio documentation and final phase gate

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-6.md`

**Interfaces:**
- Consumes: verified Phase 6 commands and measured output from Tasks 1–3.
- Produces: user-facing execution guidance, financial semantics, schema explanation, and reproducible gate evidence.

- [ ] **Step 1: Update the README**

Change current status to Phase 6 and document:

```text
PNCP -> Bronze RAW -> Silver -> Data quality gate -> Gold star schema
```

Add the load example:

```python
from govinsight.config import get_settings
from govinsight.database import create_database_engine
from govinsight.warehouse import WarehouseLoadService

engine = create_database_engine(get_settings())
result = WarehouseLoadService(engine).run_pending()
print(result.status, result.source_watermark, result.rows_loaded)
```

Explain the four dimensions, fact grain, exact equality gate, Type 1 limitation, and that contracted value will come only from the future contract fact. State explicitly that homologated value is not contracted value.

- [ ] **Step 2: Run the focused phase gate once**

```powershell
$env:GOVINSIGHT_DATABASE_URL='postgresql+psycopg://govinsight_app:govinsight_local@127.0.0.1:54320/govinsight?connect_timeout=5'
.\.venv\Scripts\python.exe -m pytest tests\integration\test_warehouse_migration.py tests\integration\test_warehouse_service.py -q -p no:cacheprovider --tb=short
```

Expected: all Phase 6 tests pass.

- [ ] **Step 3: Run the complete regression and static gate once**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short -m "not live_api" --cov=govinsight --cov-report=term-missing
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe heads
git diff --check
```

Expected: non-live tests pass, coverage remains at least 80%, Ruff and whitespace checks pass, and both Alembic commands report `20260826_0005 (head)`.

- [ ] **Step 4: Record measured evidence**

Create `docs/checkpoints/phase-6.md` with the exact test count, coverage, Ruff result, Alembic head, schema grain, reconciliation invariants, and deferred entities. Do not write expected values as if they were measured.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md docs/checkpoints/phase-6.md
git commit -m "docs: add phase 6 warehouse guide and checkpoint"
```

- [ ] **Step 6: Request final review and address only actionable findings**

Review against the Phase 6 spec, classifying findings as Critical, Important, or Minor. Fix Critical and Important issues, rerun only the affected focused test, then rerun the final gate once if source code changed.
