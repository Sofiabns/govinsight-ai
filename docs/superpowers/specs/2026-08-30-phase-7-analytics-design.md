# Phase 7 — Procurement Analytics Design

## Objective

Turn the trusted Gold procurement star schema into reusable, evidence-backed KPIs for later API, dashboard, and AI-agent phases.

## Scope

Phase 7 includes only dimensions and measures already available in Gold:

- procurement count;
- total and average estimated value;
- total and average homologated value;
- rankings by organization, state, and modality;
- monthly evolution and month-over-month growth;
- financial participation within each result set;
- deterministic value-distribution summaries and IQR outlier detection.

Supplier, category, municipality-region, contracted-value, and opportunity metrics remain deferred until trusted upstream models exist. The system must never label estimated or homologated amounts as contracted value.

## Selected Architecture

Use ordinary PostgreSQL views as the canonical metric layer and a typed `govinsight.analytics` Python package as its query interface. Views keep KPI definitions centralized and available to future consumers; the Python layer applies validated filters and returns stable models without duplicating formulas.

Materialized views are deferred because current volume does not justify refresh state or staleness. Direct ad-hoc SQL alone was rejected because it would duplicate business rules across the API, dashboard, and agents.

## Analytical Views

An Alembic migration creates:

- `gold.analytics_procurement_base`: one joined, reusable procurement row with analytical dimensions and measures;
- `gold.analytics_summary`: one overall row with count, totals, null-aware averages, and value coverage;
- `gold.analytics_by_organization`: one row per organization;
- `gold.analytics_by_state`: one row per available UF plus an explicit unknown-location group;
- `gold.analytics_by_modality`: one row per modality;
- `gold.analytics_monthly`: one row per publication month with totals, averages, and prior-month comparisons.

Filtered queries aggregate `analytics_procurement_base`; unfiltered consumers may read the summary views directly. All monetary calculations use PostgreSQL `numeric`. Averages divide only by rows where the selected measure is present. Shares return null when the corresponding overall total is zero. Monthly growth returns null when no prior calendar month exists or the prior value is zero; missing months are not silently treated as zero.

## Query Interface

The `govinsight.analytics` package contains:

- immutable result and filter models;
- repositories that read the analytical views through parameterized SQL;
- a service exposing summary, rankings, monthly trends, distribution, and outliers;
- a separate statistical module for deterministic IQR calculations.

Supported optional filters are publication date range, organization, UF, and modality. Ranking limits are bounded. Results have deterministic ordering, including stable tie-breakers.

## Distribution and Outliers

Distribution statistics use non-null homologated values by default and may explicitly select estimated values. The output includes count, minimum, quartiles, median, maximum, mean, and IQR.

An outlier is a procurement whose selected value is below `Q1 - 1.5 × IQR` or above `Q3 + 1.5 × IQR`. Detection is descriptive, not an accusation of irregularity or fraud. Empty inputs and samples too small to establish an IQR return no outliers with explicit sample metadata.

## Error Handling

Invalid periods, unsupported measures, and out-of-range limits fail before SQL execution. Database failures propagate with transaction rollback. Queries return empty collections for valid filters with no matching rows. Logs include operation, filters, and row counts, never source payloads.

## Verification

Focused integration fixtures will calculate expected values independently and validate:

- exact counts, totals, averages, null handling, and joins;
- rankings and deterministic ties;
- state unknown grouping;
- monthly growth semantics, including missing and zero prior periods;
- distribution quartiles and IQR outliers;
- filter composition and empty results;
- database migration upgrade and downgrade.

The gate runs the focused Phase 7 tests, one complete non-live regression suite, Ruff, formatting verification, and Alembic head confirmation.

## Success Criteria

Phase 7 passes when every exposed KPI reconciles with an independently calculated Gold sample, unsupported metrics are not invented, statistical outliers are reproducible, and future API/dashboard/agent consumers can reuse one documented analytical contract.
