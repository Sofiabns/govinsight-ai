# Phase 7 Procurement Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide reusable, exact procurement KPIs, rankings, trends, distributions, and statistical outliers from the trusted Gold star schema.

**Architecture:** PostgreSQL views define the canonical analytical layer. A typed Python package queries those views with validated filters and computes deterministic IQR outliers without an LLM.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, PostgreSQL 16, Alembic, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-30-phase-7-analytics-design.md`

## Global Constraints

- Use only procurement, organization, unit/UF, modality, and publication-date data already in Gold.
- Never call estimated or homologated value “contracted value”.
- Preserve monetary values as `Decimal`/PostgreSQL `numeric`; never float-convert or zero-fill source nulls.
- Defer suppliers, categories, regions, opportunity scores, and materialized views.
- Return null growth for a missing prior calendar month or zero prior value.
- Outlier labels are statistical observations, never allegations of fraud.
- Run focused tests during implementation and one complete non-live suite at the final gate.

---

### Task 1: Canonical PostgreSQL analytics views

**Files:**
- Create: `alembic/versions/20260830_0006_create_analytics_views.py`
- Create: `tests/integration/test_analytics_migration.py`

**Interfaces:**
- Consumes: Alembic revision `20260826_0005` and the Phase 6 Gold star schema.
- Produces: `gold.analytics_procurement_base`, `gold.analytics_summary`, `gold.analytics_by_organization`, `gold.analytics_by_state`, `gold.analytics_by_modality`, and `gold.analytics_monthly`.

- [x] **Step 1: Write the failing migration contract**

Assert that upgrading from `20260826_0005` creates all six views, exposes the documented columns, groups missing UF as `UNKNOWN`, and downgrades cleanly before restoring `head` in `finally`.

```python
assert expected_views <= set(inspector.get_view_names(schema="gold"))
summary = connection.execute(sa.text("SELECT * FROM gold.analytics_summary")).mappings().one()
assert summary["procurement_count"] == 3
assert summary["estimated_total"] == Decimal("600.0000")
assert summary["homologated_average"] == Decimal("250.0000")
```

- [x] **Step 2: Run RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_analytics_migration.py -q -p no:cacheprovider --tb=short
```

Expected: fail because revision `20260830_0006` and the views do not exist.

- [x] **Step 3: Create the reversible migration**

Set `revision = "20260830_0006"` and `down_revision = "20260826_0005"`. Build `analytics_procurement_base` by joining fact to all required dimensions. Define aggregate views with `COUNT(*)`, `SUM`, `AVG`, explicit non-null coverage, stable identifiers, and `LAG` keyed by calendar month. Growth uses the lagged value only when its month is exactly one calendar month earlier; otherwise it is null. Use `NULLIF` for share and growth denominators. Drop dependent views before the base view in `downgrade()`.

- [x] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_analytics_migration.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check alembic\versions\20260830_0006_create_analytics_views.py tests\integration\test_analytics_migration.py
git add alembic/versions/20260830_0006_create_analytics_views.py tests/integration/test_analytics_migration.py
git commit -m "feat: add canonical procurement analytics views"
```

---

### Task 2: Typed KPI and statistical query service

**Files:**
- Create: `src/govinsight/analytics/__init__.py`
- Create: `src/govinsight/analytics/models.py`
- Create: `src/govinsight/analytics/repositories.py`
- Create: `src/govinsight/analytics/statistics.py`
- Create: `src/govinsight/analytics/service.py`
- Create: `tests/integration/test_analytics_service.py`
- Create: `tests/unit/analytics/test_statistics.py`

**Interfaces:**
- Consumes: views from Task 1 and a SQLAlchemy `Engine`.
- Produces: `AnalyticsFilters`, `Measure`, `RankDimension`, `AnalyticsSummary`, `RankingRow`, `MonthlyTrend`, `DistributionSummary`, `OutlierResult`, and `AnalyticsService` methods `summary`, `rank`, `monthly_trend`, `distribution`, and `outliers`.

- [x] **Step 1: Write failing model and statistics tests**

Validate reversed periods, limit bounds `1..100`, supported measures, exact Decimal quartiles, empty samples, and outlier fences.

```python
values = [Decimal(value) for value in ("10", "11", "12", "13", "100")]
result = describe(values)
assert result.q1 == Decimal("11")
assert result.q3 == Decimal("13")
assert result.upper_fence == Decimal("16.0")
assert detect_outliers(values, result) == [Decimal("100")]
```

- [x] **Step 2: Implement immutable models and deterministic statistics**

Use Pydantic frozen models, `Measure.ESTIMATED`/`HOMOLOGATED`, `RankDimension.ORGANIZATION`/`STATE`/`MODALITY`, UTC-safe date filters, and Decimal-only linear interpolation for quartiles. Samples with fewer than four non-null values return distribution metadata and no outliers.

- [x] **Step 3: Write failing service integration tests**

Seed a scoped Gold sample and independently assert exact summary values, filter composition, deterministic ranking ties, `UNKNOWN` state grouping, monthly growth gaps/zero denominators, empty results, distribution, and returned PNCP evidence for outliers.

```python
summary = service.summary(AnalyticsFilters(uf="SP"))
assert summary.procurement_count == 2
assert summary.homologated_total == Decimal("500.0000")
assert service.rank("organization", limit=10)[0].rank == 1
assert service.monthly_trend()[1].homologated_growth_rate is None
```

- [x] **Step 4: Implement repository and service**

Build one parameterized base query, compose only validated filters, aggregate with SQLAlchemy expressions, and order rankings by selected total descending then stable natural key ascending. The service logs operation and row count, owns connections with `engine.connect()`, and maps rows into immutable models.

- [x] **Step 5: Run focused GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\analytics tests\integration\test_analytics_service.py -q -p no:cacheprovider --tb=short
.\.venv\Scripts\ruff.exe check src\govinsight\analytics tests\unit\analytics tests\integration\test_analytics_service.py
git add src/govinsight/analytics tests/unit/analytics tests/integration/test_analytics_service.py
git commit -m "feat: add typed procurement analytics service"
```

---

### Task 3: Portfolio documentation and final gate

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-7.md`
- Modify: `docs/superpowers/plans/2026-08-30-phase-7-analytics.md`

**Interfaces:**
- Consumes: measured Phase 7 behavior and verification output.
- Produces: truthful KPI semantics, usage examples, limitations, and final evidence.

- [x] **Step 1: Document the analytical contract**

Add a concise README section showing the five service operations, estimated versus homologated semantics, null/growth behavior, and the supplier/category/region limitations. Record only measured test and coverage numbers in the checkpoint.

- [x] **Step 2: Run the final gate once**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short -m "not live_api"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe heads
git diff --check
```

Expected: all non-live tests pass; Ruff and formatting are clean; current and head are `20260830_0006`.

- [x] **Step 3: Close the plan and commit**

Mark every checkbox complete, record the exact gate evidence in `docs/checkpoints/phase-7.md`, and commit:

```powershell
git add README.md docs/checkpoints/phase-7.md docs/superpowers/plans/2026-08-30-phase-7-analytics.md
git commit -m "docs: add phase 7 analytics guide and checkpoint"
```
