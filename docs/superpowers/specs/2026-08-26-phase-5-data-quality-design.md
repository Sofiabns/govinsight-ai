# Phase 5 — Data Quality Design

**Date:** 2026-08-26  
**Status:** Approved for planning  
**Scope:** PostgreSQL-native quality gate for `silver.procurement`

## 1. Objective

Add a deterministic quality stage between Silver and the future Gold warehouse. The stage must
measure the current procurement dataset, persist rule-level evidence, calculate a score from 0 to
100, block its own watermark when critical rules fail, and detect deliberately injected invalid
data without changing or deleting Silver records.

This phase remains procurement-only. Contracts, items, IBGE enrichment, Gold tables, orchestration,
API, dashboard and agents stay outside the slice.

## 2. Technology decision

Use SQLAlchemy Core and PostgreSQL queries rather than Pandera or Great Expectations.

SQL-native rules are the best fit because the trusted dataset already lives in PostgreSQL, the
checks include database constraints and referential integrity, and aggregate SQL avoids loading the
table into application memory. It also keeps each rule transparent in interviews and adds no
framework dependency.

Alternatives rejected for this phase:

- **Pandera:** useful for DataFrame pipelines, but would duplicate database reads and require a
  DataFrame dependency for checks PostgreSQL performs directly.
- **Great Expectations:** offers extensive reporting, but introduces configuration and runtime
  complexity beyond the needs of the first vertical slice.

These tools can be reconsidered only if a later source is transformed primarily in DataFrames.

## 3. Quality model

### 3.1 Dimensions and weights

The score is deterministic and uses five dimensions:

| Dimension | Weight | Purpose |
|---|---:|---|
| Completeness | 30% | Required business fields contain meaningful values |
| Validity | 25% | Identifiers, domains and numeric values fit accepted rules |
| Uniqueness | 20% | Current-state business keys and lineage are not duplicated |
| Consistency | 15% | Dates and related business attributes agree |
| Integrity | 10% | Silver lineage resolves to an existing Bronze response |

For each evaluated rule:

```text
rule_score = 100 × (checked_count - failed_count) / checked_count
```

Rules with no applicable rows are `NOT_EVALUATED` and do not reduce their dimension. A completely
empty dataset fails the blocking `DATASET_NOT_EMPTY` rule and receives score 0. A dimension score is
the mean of its evaluated rule scores; the final score is the weighted mean of the five dimensions,
rounded to two decimal places.

The score communicates degree of quality; it does not override blocking severity. A run fails when
any blocking rule exceeds its threshold, regardless of the numeric score.

### 3.2 Initial rules

| Code | Dimension | Blocking condition |
|---|---|---|
| `DATASET_NOT_EMPTY` | Completeness | No procurement rows exist |
| `REQUIRED_TEXT_PRESENT` | Completeness | Required text is null or blank |
| `REQUIRED_DATE_PRESENT` | Completeness | Publication or global-update date is null |
| `CNPJ_FORMAT_VALID` | Validity | Organization CNPJ is not 14 digits |
| `UF_DOMAIN_VALID` | Validity | Non-null UF is outside the 27 official codes |
| `IBGE_FORMAT_VALID` | Validity | Non-null municipality code is not 7 digits |
| `MONEY_RANGE_VALID` | Validity | Monetary value is negative or exceeds `numeric(19,4)` |
| `NATURAL_KEY_UNIQUE` | Uniqueness | A PNCP control number appears more than once |
| `SOURCE_POSITION_UNIQUE` | Uniqueness | A RAW response/index pair appears more than once |
| `PROPOSAL_WINDOW_VALID` | Consistency | Proposal closing precedes opening |
| `PURCHASE_YEAR_CONSISTENT` | Consistency | `ano_compra` disagrees with the PNCP key year |
| `BRONZE_LINEAGE_VALID` | Integrity | Source RAW response does not exist |

Some conditions are already protected by Silver constraints. Rechecking them is intentional: the
quality report proves the invariant at the stage boundary and detects manual or legacy corruption.

`ROW_VOLUME_ANOMALY` is a non-blocking operational warning. After at least three prior successful
runs, it compares the current row count with the median of up to ten prior runs. A deviation above
50% is recorded as a warning. It does not affect the five-dimension score.

## 4. Persistence

Create two control tables through Alembic revision `20260826_0004`.

### `control.data_quality_run`

- identity primary key;
- dataset and stage;
- source Silver watermark;
- status: `RUNNING`, `PASSED` or `FAILED`;
- start and finish timestamps in UTC;
- rows evaluated;
- score `numeric(5,2)`;
- blocking-failure count;
- safe error code when execution itself fails.

The pair `(dataset, source_watermark)` is unique, making a quality snapshot idempotent.

### `control.data_quality_result`

- run foreign key;
- stable rule code;
- dimension and severity;
- status: `PASSED`, `FAILED`, `WARNING` or `NOT_EVALUATED`;
- checked and failed counts;
- rule score `numeric(5,2)` when evaluated;
- safe aggregate details as JSONB;
- evaluation timestamp in UTC.

The pair `(run_id, rule_code)` is unique. Results never store source payloads, free-form PNCP text,
credentials or exception chains.

## 5. Execution flow

`DataQualityService.run_pending()` follows this sequence:

1. Read the confirmed Silver procurement watermark.
2. Return a no-op result when no newer Silver snapshot exists.
3. Create or recover the unique quality run for that source watermark.
4. Execute registered aggregate rules against `silver.procurement`.
5. Calculate rule, dimension and overall scores in Python using `Decimal`.
6. Persist all rule results and finalize the run in one transaction.
7. Advance `control.etl_watermark` for stage `quality` only when every blocking rule passes.
8. On an execution exception, record a safe failure code without copying SQL parameters, data or
   payloads into persisted errors.

A quality failure is an auditable outcome, not an exception: results and the failed run remain
available, while the quality watermark stays at the last passing Silver snapshot. Infrastructure or
query failures raise a safe application exception after the failed run is recorded.

The service never edits Silver. Operators correct the upstream record or transformation and run the
quality stage again against a newer Silver watermark. Re-evaluating the same snapshot returns its
existing run rather than duplicating evidence.

## 6. Components

```text
src/govinsight/quality/
├── models.py        Immutable rule and run results
├── rules.py         Explicit SQL rule registry
├── scoring.py       Decimal dimension and overall score calculation
├── repositories.py Run, result, history and watermark persistence
├── service.py       Idempotent quality-gate workflow
└── tables.py        SQLAlchemy metadata
```

The rule registry describes code, dimension, weight, severity and the aggregate SQL statement. The
repository owns persistence only; the service owns transaction boundaries; the scoring module has
no database dependency.

## 7. Error handling and security

- Rule failures expose only stable codes and aggregate counts.
- Database and infrastructure errors become safe typed exceptions.
- No RAW body, rejected payload, SQL parameter dump or credential is persisted or logged.
- Counts and scores are non-negative and constrained in PostgreSQL.
- Watermarks are monotonic and scoped by pipeline, dataset and stage.
- A failed quality run cannot unlock the future Gold stage.

## 8. Lean verification strategy

Use three focused test layers:

1. **Scoring unit test:** exact dimension weights, rounding, non-evaluated rules and empty-dataset
   behavior.
2. **Migration integration test:** tables, types, unique keys, foreign keys, checks, downgrade and
   restore on real PostgreSQL.
3. **Service integration test:** clean data passes; direct injection of a blank required value and
   invalid UF is detected; failed quality does not advance its watermark; a newer corrected Silver
   snapshot passes; replay is idempotent; persisted details contain no injected source value.

The final gate runs lint, format, the complete local/PostgreSQL suite, coverage of at least 80%,
Alembic head verification and a compact bug hunt. The live PNCP test is not repeated because this
phase operates exclusively on the local Silver snapshot.

## 9. Portfolio outcome

The phase demonstrates database-native data observability rather than a collection of assertions:
versioned rules, weighted scoring, persisted evidence, blocking semantics, idempotent snapshots,
historical volume comparison and explicit separation between bad data and pipeline failure.

## 10. Completion criteria

Phase 5 passes only when:

- invalid injected data is detected by the expected stable rules;
- a blocking failure persists evidence but does not advance the quality watermark;
- a clean newer snapshot advances the watermark exactly once;
- the score is reproducible from stored rule counts;
- the migration is reversible and at `20260826_0004 (head)`;
- all relevant tests and quality gates pass;
- `docs/checkpoints/phase-5.md` contains measured, non-invented results.
