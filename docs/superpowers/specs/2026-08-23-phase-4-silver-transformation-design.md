# Phase 4 Silver Procurement Transformation Design

Date: 2026-08-23  
Status: approved for planning

## Goal

Transform procurement records from immutable PNCP Bronze responses into one typed, current-state
Silver table. Preserve source lineage, quarantine invalid individual records, and advance the
Silver watermark only after a RAW response is processed atomically.

This phase starts with procurements only. Contracts, items, results, IBGE enrichment, data-quality
scoring, Gold dimensions and orchestration remain outside this slice.

## Architecture

```text
bronze.raw_api_response (dataset = procurements)
                    |
                    v
       parse exact response envelope
                    |
          +---------+---------+
          |                   |
          v                   v
 valid normalized record   invalid record
          |                   |
          v                   v
 silver.procurement       silver.rejected_record
          +---------+---------+
                    |
                    v
 control.etl_watermark (stage = silver)
```

One RAW response is the transaction boundary. Procurement UPSERTs, rejection inserts and the
watermark update commit together. A failure rolls back the entire response.

## Components

- `transform/procurement/models.py`: typed input and normalized procurement models.
- `transform/procurement/parser.py`: envelope parsing, normalization and safe validation errors.
- `transform/tables.py`: SQLAlchemy Core definitions for the two Silver tables.
- `transform/repositories.py`: conditional procurement UPSERT, quarantine and watermark access.
- `transform/service.py`: ordered RAW selection and per-response transaction coordination.
- Alembic revision: creates Silver tables, constraints, indexes and foreign keys.

Each component has one responsibility. No transformation logic is placed in API handlers,
notebooks or the Bronze repositories.

## Silver procurement model

`silver.procurement` stores one current row per `numero_controle_pncp`.

Core identity and lineage:

- `numero_controle_pncp` text primary key;
- `source_raw_response_id` foreign key to `bronze.raw_api_response.id`;
- `source_record_index` non-negative integer;
- `normalized_sha256` lowercase SHA-256 of canonical normalized data;
- `created_at` and `updated_at` timezone-aware timestamps.

Typed business fields:

- procurement: `ano_compra`, `sequencial_compra`, `numero_compra`, `processo`, `objeto_compra`,
  `srp`;
- organization: `orgao_cnpj`, `orgao_razao_social`, `poder_id`, `esfera_id`;
- unit/location: `codigo_unidade`, `nome_unidade`, `codigo_ibge`, `municipio_nome`, `uf_sigla`,
  `uf_nome`;
- classifications: modality, dispute mode, legal basis, situation and instrument codes/names;
- dates: inclusion, PNCP publication, update, global update, proposal opening and closing;
- money: `valor_total_estimado` and nullable `valor_total_homologado` as `numeric(19,4)`.

PNCP timestamps without an offset remain PostgreSQL `timestamp without time zone`. The
transformation never invents a timezone. Monetary values use Python `Decimal` and PostgreSQL
`numeric`, never binary floats.

Required values are the natural key, organization CNPJ/name, unit code/name, object, procurement
year/sequence, modality, publication date and global update date. Values empirically nullable in
Discovery, including `valorTotalHomologado`, remain nullable and are never replaced with zero.

## Normalization and update rules

- Trim surrounding whitespace; an empty optional string becomes null.
- Preserve case and meaningful internal text. Do not rewrite procurement descriptions.
- Validate CNPJ as 14 digits, UF as two letters, IBGE code as seven digits when present, positive
  natural-key numbers, non-negative money and coherent proposal dates.
- Ignore unknown payload fields in Silver; the complete source remains available in Bronze.
- Calculate the normalized hash from a canonical UTF-8 JSON representation of the typed model.
- Insert a new natural key.
- Skip an existing row when its normalized hash is unchanged.
- Update a changed row only when `data_atualizacao_global` is newer, or when it is equal and the
  incoming RAW id is greater. Older source versions cannot regress Silver state.

## Quarantine

`silver.rejected_record` contains:

- identity and timestamps;
- `source_raw_response_id` and `source_record_index`;
- nullable `natural_key` when it can be recovered safely;
- a deterministic list of safe error codes;
- transformer version.

The unique key `(source_raw_response_id, source_record_index)` prevents duplicate quarantines.
The table does not duplicate the full record, response body, supplier identifiers or invalid
values. Investigation follows the RAW foreign key under database access controls.

An invalid record is quarantined without blocking valid siblings. An unreadable JSON document,
invalid response envelope or database failure aborts the whole RAW response and does not advance
the watermark.

## Incremental processing and idempotency

The service reads `bronze.raw_api_response` rows with dataset `procurements`, ordered by id, after
the Silver watermark. The watermark key is:

```text
pipeline_name = silver_procurement
dataset = procurements
stage = silver
watermark_value = {"last_raw_response_id": <id>}
```

Each successfully processed response advances this value in the same transaction as its Silver
writes. Replaying a response creates neither duplicate procurements nor duplicate rejections.
This stage does not change the extraction checkpoint.

## Errors and observability

Validation produces stable codes such as `MISSING_REQUIRED`, `INVALID_CNPJ`, `INVALID_DATE`,
`INVALID_DECIMAL` and `INCONSISTENT_DATE_RANGE`. Error logs contain RAW ids, record indexes and
codes only. They never contain the response body or rejected values.

The service reports measured counts for responses processed, records received, inserted, updated,
unchanged and rejected. Durable run orchestration is deferred to Phase 8; Phase 4 exposes the
counts without introducing a second orchestration system.

## Lean verification

Verification is intentionally risk-based:

1. focused unit coverage for one valid fixture and representative validation failures;
2. one migration integration test for the two tables and key constraints;
3. one PostgreSQL end-to-end test covering valid insert, quarantine, replay idempotency and a newer
   source update;
4. lint, format and the full test suite once at the Phase 4 gate.

Tests are repeated only after a real failure or material correction.

## Acceptance criteria

- Real Bronze procurement responses produce typed Silver rows.
- Invalid individual records are safely quarantined while valid siblings commit.
- The transformation is atomic per RAW response, incremental and idempotent.
- Older PNCP versions cannot overwrite newer Silver state.
- Monetary nulls and offset-free timestamps retain their semantics.
- Lineage reaches the exact Bronze response and record index.
- No contract, item, Gold, dashboard, agent or orchestration work is introduced.
- The Phase 4 checkpoint records only freshly measured results.

