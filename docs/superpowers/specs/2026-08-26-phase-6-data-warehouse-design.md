# Phase 6 — Data Warehouse Design

## Objective

Create the first trustworthy Gold analytical slice for PNCP procurements. The warehouse must expose a real star schema, preserve financial meaning, depend on the Phase 5 quality gate, and remain idempotent under repeated execution.

## Scope

Phase 6 models only the procurement grain already available in `silver.procurement`.

Included:

- role-playing date dimension;
- organization, purchasing unit/location, and modality dimensions;
- one procurement fact row per `numero_controle_pncp`;
- exact reconciliation of row counts and monetary measures;
- quality-aware Gold watermark;
- database migration, load service, repositories, integration tests, and portfolio documentation.

Deferred until their trusted Silver sources exist:

- contracts and committed/contracted amounts;
- suppliers;
- procurement items and item results;
- category classification;
- IBGE region enrichment;
- slowly changing history.

`valor_total_homologado` is not a substitute for contracted value. Phase 6 does not expose a `valor_contratado` measure.

## Considered Approaches

### 1. Procurement star schema — selected

Build focused dimensions and `gold.fact_procurement` from the existing Silver dataset. This demonstrates dimensional modeling without inventing unavailable entities and prepares stable inputs for APIs and dashboards.

### 2. Single wide Gold table

This would be simpler to load but would repeat descriptive attributes, weaken join and integrity guarantees, and provide little portfolio evidence of warehouse design.

### 3. Full analytical constellation

Adding contracts, suppliers, items, and results now would offer broader analytics, but those entities do not yet have trusted Silver pipelines. Implementing them in this phase would either couple Gold directly to raw API payloads or manufacture unsupported semantics.

## Dimensional Model

### `gold.dim_date`

One row per calendar date used by a procurement. The deterministic primary key is an integer in `YYYYMMDD` format.

Attributes:

- `date_key`;
- `full_date`;
- `day`;
- `month`;
- `quarter`;
- `year`;
- `iso_weekday`.

The fact uses the dimension in three roles: publication, proposal opening, and proposal closing. Opening and closing keys are nullable. Naive PNCP timestamps are converted to dates without silently assigning a time zone.

### `gold.dim_organization`

One current row per organization CNPJ.

- surrogate primary key `organization_key`;
- natural key `orgao_cnpj`;
- `orgao_razao_social`;
- `poder_id`;
- `esfera_id`.

Attributes use Type 1 updates because the current Silver model does not retain historical versions.

### `gold.dim_unit`

One current row per purchasing unit. Its natural key is `(orgao_cnpj, codigo_unidade)` because a unit code is not assumed to be globally unique.

- surrogate primary key `unit_key`;
- organization CNPJ and unit code;
- unit name;
- IBGE municipality code;
- municipality name;
- state abbreviation and name.

Location stays attached to the unit for this vertical slice. A separate locality dimension and region attribute are deferred until official IBGE enrichment is introduced.

### `gold.dim_modality`

One current row per PNCP modality code.

- surrogate primary key `modality_key`;
- natural key `modalidade_id`;
- `modalidade_nome`.

Descriptions use Type 1 updates.

### `gold.fact_procurement`

Grain: one current procurement per `numero_controle_pncp`.

Keys and lineage:

- surrogate primary key `procurement_key`;
- unique degenerate key `numero_controle_pncp`;
- foreign keys to organization, unit, modality, and the three date roles;
- `source_raw_response_id`;
- `normalized_sha256`.

Descriptive transaction attributes:

- procurement year and sequence;
- procurement number;
- SRP flag;
- object description;
- selected status and instrument identifiers/names needed by downstream analysis.

Measures:

- `valor_total_estimado numeric(19,4)`;
- `valor_total_homologado numeric(19,4)`.

The fact retains null monetary values as null. It never coerces them to zero.

## Load Architecture

The `govinsight.warehouse` package will separate table metadata, repositories, result/error models, and orchestration service, following the existing Raw, Silver, and Quality boundaries.

The service serializes loads with a PostgreSQL session advisory lock acquired before opening one
bounded database transaction with `REPEATABLE READ` isolation:

1. acquire the warehouse session lock;
2. open the repeatable-read transaction and read Gold, Silver, and Quality watermarks;
3. require Silver and Quality to be equal and greater than zero;
4. return a no-op when Gold already represents that snapshot;
5. reject a Gold watermark ahead of the approved source snapshot;
6. upsert each dimension by its natural key with Type 1 semantics;
7. upsert the fact by `numero_controle_pncp`;
8. validate the completed star schema against Silver;
9. advance the Gold watermark only after all validations pass;
10. commit the transaction and release the session lock.

The Gold watermark uses the existing `control.etl_watermark` table with dataset `procurements`, stage `gold`, and a dedicated warehouse pipeline identifier. It stores the same `last_raw_response_id` snapshot marker used by Silver and Quality.

## Quality-Gate Semantics

Gold may load only when:

```text
silver_watermark == quality_watermark > gold_watermark
```

Exact equality is essential because Silver is a mutable current-state table. If Silver advances to a snapshot that fails quality, Gold cannot safely reconstruct an older passing snapshot from it. The loader therefore blocks until the current Silver snapshot itself passes quality.

No-op is valid only when:

```text
silver_watermark == quality_watermark == gold_watermark
```

Silver and Quality watermark rows are required; their absence raises
`APPROVED_SNAPSHOT_UNAVAILABLE`. An absent Gold watermark represents the first load and starts at
zero. Malformed, regressed, or contradictory state raises a warehouse state error and leaves Gold
unchanged.

## Reconciliation Invariants

Before advancing the Gold watermark, SQL validations must prove:

- every Silver procurement has exactly one fact row;
- every fact row has a matching Silver procurement;
- every non-null fact foreign key resolves to its dimension;
- the PNCP control key is unique;
- dimension natural keys are unique;
- fact and Silver sums of estimated value match exactly;
- fact and Silver sums of homologated value match exactly;
- fact null counts for both monetary measures match Silver;
- fact lineage identifiers and normalized hashes match Silver.

Monetary comparisons use PostgreSQL `numeric`; application code never converts them to floating point. Any invariant failure rolls back the entire transaction, including dimension/fact changes and the Gold watermark.

## Idempotency and Updates

Repeated execution for an already loaded approved snapshot returns a no-op and performs no writes.

When a later approved Silver snapshot arrives:

- dimension descriptions are updated in place;
- changed fact attributes and measures are updated in place;
- unchanged facts remain stable;
- new facts are inserted.

Phase 6 performs no source-driven deletion because the upstream Silver pipeline currently has no authoritative deletion signal. This limitation is documented rather than inferred from missing records.

## Error Handling

Expected state failures use explicit warehouse error codes/messages for:

- unavailable approved snapshot;
- Silver/Quality mismatch;
- invalid or regressed watermark;
- reconciliation failure.

Unexpected database errors propagate after rollback. Logs contain snapshot identifiers and aggregate counts, but no complete source payloads.

## Verification Strategy

Testing remains focused:

- migration test for Gold tables, keys, constraints, and indexes;
- integration test for a complete approved load, dimension joins, counts, financial reconciliation, and watermark advancement;
- replay test proving no-op behavior;
- update test proving Type 1 dimension and fact upserts;
- blocked-load test for Silver/Quality mismatch;
- rollback test proving a failed reconciliation cannot advance the watermark.
- concurrent-load test proving exactly one load and one no-op without serialization failure.

Final phase verification runs the focused Phase 6 suite, the existing regression suite once, Ruff once, and confirms the Alembic head.

## Deliverables

- Alembic revision creating the Gold star schema;
- `govinsight.warehouse` loading package;
- focused migration and service integration coverage;
- README usage and metric-semantics update;
- `docs/checkpoints/phase-6.md` with verification evidence.

## Success Criteria

Phase 6 passes when an approved Silver snapshot can be loaded idempotently into the Gold star schema, all PK/FK/join/count/financial invariants hold, failed or unapproved snapshots cannot advance Gold, and the documentation clearly distinguishes estimated, homologated, and contracted amounts.
