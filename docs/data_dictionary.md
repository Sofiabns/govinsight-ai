# Data dictionary

## Bronze and control

| Object | Grain | Purpose |
|---|---|---|
| `bronze.raw_api_response` | One successful HTTP response version | Exact PNCP evidence, request identity and SHA-256 hash |
| `control.extraction_checkpoint` | One extraction query scope | Last committed source page for safe resume |
| `control.etl_run` | One pipeline execution | Operational status and timestamps |
| `control.etl_watermark` | One pipeline stage | Last trusted source position |
| `control.data_quality_run` | One evaluated Silver snapshot | Aggregate score and gate status |
| `control.data_quality_result` | One rule in one run | Checked/failed counts and rule evidence |

## Silver

| Object | Grain | Important fields |
|---|---|---|
| `silver.procurement` | Current valid record per PNCP control number | control number, source dates, organization, unit, modality, estimated and homologated totals, RAW lineage |
| `silver.rejected_record` | One invalid source record | RAW id, record index and bounded reason codes |

## Gold star

| Object | Grain | Role |
|---|---|---|
| `gold.dim_date` | One calendar day | Publication date analysis |
| `gold.dim_organization` | One purchasing organization | CNPJ and current legal name |
| `gold.dim_unit` | One purchasing unit/location | Unit identity and state fields |
| `gold.dim_modality` | One procurement modality | Official modality identity and description |
| `gold.fact_procurement` | One current procurement control number | Dimension keys, separate estimated/homologated measures and lineage |

## Analytical views

| View | Output |
|---|---|
| `gold.analytics_procurement_base` | Denormalized trusted procurement rows |
| `gold.analytics_summary` | Overall counts, totals and averages |
| `gold.analytics_by_organization` | Organization totals, averages and shares |
| `gold.analytics_by_state` | State totals, averages and shares |
| `gold.analytics_by_modality` | Modality totals, averages and shares |
| `gold.analytics_monthly` | Monthly totals, averages and consecutive-month growth |

`valor_total_estimado` and `valor_total_homologado` are nullable exact monetary measures. A missing
value is not converted to zero. Homologated value is not contract value, and no supplier/category
metric is claimed because those trusted dimensions are not present in this release.
