# Phase 4 Silver Procurement Transformation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Bronze PNCP procurement responses into an incremental, idempotent and typed
Silver table with safe record-level quarantine.

**Architecture:** Process Bronze procurement responses in id order and use one transaction per RAW
response. Valid records are conditionally UPSERTed, invalid records are quarantined, and the Silver
watermark advances atomically after both operations.

**Tech Stack:** Python 3.12, Pydantic 2, SQLAlchemy Core 2, PostgreSQL 16, Alembic and pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-phase-4-silver-transformation-design.md`

## Global Constraints

- Scope is procurements only; do not add contracts, items, IBGE, Gold or orchestration.
- Preserve Bronze response text and extraction checkpoint unchanged.
- Use `Decimal` and PostgreSQL `numeric(19,4)` for money.
- Keep PNCP timestamps without offset as timezone-naive values.
- Store safe error codes and lineage only; never copy rejected payloads into quarantine or logs.
- An individual invalid record does not block valid siblings.
- An invalid envelope, unreadable JSON or database error rolls back the whole RAW response.
- Advance `control.etl_watermark` only in the same transaction as Silver writes.
- Keep verification lean: focused tests per task and one full gate at the end.

---

### Task 1: Typed procurement normalization

**Files:**
- Create: `src/govinsight/transform/__init__.py`
- Create: `src/govinsight/transform/procurement/__init__.py`
- Create: `src/govinsight/transform/procurement/models.py`
- Create: `src/govinsight/transform/procurement/parser.py`
- Create: `tests/unit/transform/test_procurement.py`

**Interfaces:**
- Consumes: one dictionary from PNCP envelope `data[index]`.
- Produces: `parse_procurement(record: object, *, raw_response_id: int, record_index: int) ->
  ProcurementParseResult`.
- Produces: `NormalizedProcurement`, `RejectedProcurement`, `ProcurementParseResult`.

- [x] **Step 1: Write the focused failing test**

Use the real procurement fixture. Assert that the first record becomes a normalized object with
`numero_controle_pncp`, `Decimal("0.0")`, nullable homologated value, naive datetimes, stripped
text, correct lineage inputs and a deterministic 64-character hash. In the same test module, pass
a copy with invalid CNPJ and proposal date range and assert only safe codes are returned:

```python
result = parse_procurement(record, raw_response_id=41, record_index=0)
assert result.procurement is not None
assert result.procurement.numero_controle_pncp == "13183513000127-1-000146/2025"
assert result.procurement.valor_total_estimado == Decimal("0.0")
assert result.procurement.valor_total_homologado is None

rejected = parse_procurement(invalid, raw_response_id=41, record_index=1)
assert rejected.rejection is not None
assert rejected.rejection.error_codes == ("INCONSISTENT_DATE_RANGE", "INVALID_CNPJ")
assert "131835" not in repr(rejected.rejection)
```

- [x] **Step 2: Run RED**

Run: `pytest tests/unit/transform/test_procurement.py -v -p no:cacheprovider`

Expected: collection fails because `govinsight.transform.procurement` does not exist.

- [x] **Step 3: Implement immutable models and parser**

Define frozen Pydantic models. `NormalizedProcurement` contains the fields listed in the spec,
using snake_case names, `Decimal | None`, `datetime | None`, `date` only where the PNCP field is a
date, and these lineage values:

```python
class NormalizedProcurement(BaseModel):
    model_config = ConfigDict(frozen=True)
    numero_controle_pncp: str
    source_raw_response_id: int
    source_record_index: int
    normalized_sha256: str
    srp: bool
    orgao_cnpj: str
    orgao_razao_social: str
    poder_id: str | None
    esfera_id: str | None
    ano_compra: int
    sequencial_compra: int
    numero_compra: str | None
    codigo_unidade: str
    nome_unidade: str
    codigo_ibge: str | None
    municipio_nome: str | None
    uf_sigla: str | None
    uf_nome: str | None
    amparo_legal_codigo: int | None
    amparo_legal_nome: str | None
    amparo_legal_descricao: str | None
    modalidade_id: int
    modalidade_nome: str
    modo_disputa_id: int | None
    modo_disputa_nome: str | None
    situacao_compra_id: int | None
    situacao_compra_nome: str | None
    tipo_instrumento_codigo: int | None
    tipo_instrumento_nome: str | None
    data_inclusao: datetime | None
    data_publicacao_pncp: datetime
    data_atualizacao: datetime | None
    data_atualizacao_global: datetime
    data_abertura_proposta: datetime | None
    data_encerramento_proposta: datetime | None
    processo: str | None
    objeto_compra: str
    informacao_complementar: str | None
    link_sistema_origem: str | None
    link_processo_eletronico: str | None
    justificativa_presencial: str | None
    usuario_nome: str | None
    valor_total_estimado: Decimal | None
    valor_total_homologado: Decimal | None


class RejectedProcurement(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_raw_response_id: int
    source_record_index: int
    natural_key: str | None
    error_codes: tuple[str, ...]
    transformer_version: str = "1"


class ProcurementParseResult(BaseModel):
    procurement: NormalizedProcurement | None = None
    rejection: RejectedProcurement | None = None
```

The public signature is `parse_procurement(record: object, *, raw_response_id: int,
record_index: int) -> ProcurementParseResult`.

Build a candidate dictionary from the observed PNCP keys. Trim surrounding strings, convert empty
optional strings to `None`, parse monetary values through `Decimal(str(value))`, and parse ISO
datetimes with `datetime.fromisoformat`. Collect deterministic sorted codes; never include values
or Pydantic messages. Hash canonical JSON with sorted keys, UTF-8 and compact separators after all
typed business values are serialized to strings; exclude lineage fields and `normalized_sha256`
itself from the hash input.

- [x] **Step 4: Run GREEN and quality checks**

Run: `pytest tests/unit/transform/test_procurement.py -v -p no:cacheprovider`

Run: `ruff check src/govinsight/transform tests/unit/transform`

Expected: focused tests and lint pass.

- [x] **Step 5: Commit**

```powershell
git add src/govinsight/transform tests/unit/transform
git commit -m "feat: add typed procurement normalization"
```

---

### Task 2: Silver schema and migration

**Files:**
- Create: `src/govinsight/transform/tables.py`
- Create: `alembic/versions/20260823_0003_create_silver_procurement.py`
- Create: `tests/integration/test_silver_migration.py`

**Interfaces:**
- Consumes: field types from `NormalizedProcurement` and `RejectedProcurement`.
- Produces: SQLAlchemy tables `procurement` and `rejected_record`.
- Produces: Alembic revision `20260823_0003`, down revision `20260817_0002`.

- [x] **Step 1: Write the migration test first**

Upgrade from `20260817_0002` to head on real PostgreSQL. Reflect both Silver tables and assert:

```python
assert inspector.get_pk_constraint("procurement", schema="silver")["constrained_columns"] == [
    "numero_controle_pncp"
]
assert {c["name"] for c in inspector.get_columns("rejected_record", schema="silver")} >= {
    "source_raw_response_id",
    "source_record_index",
    "error_codes",
}
```

Also assert the two RAW foreign keys, quarantine uniqueness, hash/CNPJ/IBGE/UF checks and monetary
non-negative checks. Downgrade to `20260817_0002`, confirm both Silver tables disappear, then
restore head in `finally`.

- [x] **Step 2: Run RED**

Run with `GOVINSIGHT_DATABASE_URL` set:

`pytest tests/integration/test_silver_migration.py -v -p no:cacheprovider`

Expected: FAIL because revision `20260823_0003` and Silver tables do not exist.

- [x] **Step 3: Implement table metadata and migration**

Create `silver.procurement` with text natural-key PK, lineage FK/index, typed business columns,
`numeric(19,4)` money, naive PNCP timestamps, normalized hash, and timezone-aware audit timestamps.
Create `silver.rejected_record` with identity PK, lineage FK, non-negative record index, nullable
natural key, `TEXT[]` safe codes, transformer version and rejection time.

Required constraints:

```text
ck_silver_procurement_cnpj: orgao_cnpj ~ '^[0-9]{14}$'
ck_silver_procurement_hash: normalized_sha256 ~ '^[0-9a-f]{64}$'
ck_silver_procurement_uf: uf_sigla IS NULL OR uf_sigla ~ '^[A-Z]{2}$'
ck_silver_procurement_ibge: codigo_ibge IS NULL OR codigo_ibge ~ '^[0-9]{7}$'
ck_silver_procurement_values: monetary fields are null or >= 0
ck_silver_procurement_proposal_window: either date is null or closing >= opening
uq_silver_rejected_source_record: (source_raw_response_id, source_record_index)
```

Downgrade drops quarantine first, then procurement.

- [x] **Step 4: Run GREEN**

Run: `pytest tests/integration/test_silver_migration.py -v -p no:cacheprovider`

Expected: migration test passes and restores `20260823_0003 (head)`.

- [x] **Step 5: Commit**

```powershell
git add src/govinsight/transform/tables.py alembic/versions/20260823_0003_create_silver_procurement.py tests/integration/test_silver_migration.py
git commit -m "feat: create silver procurement schema"
```

---

### Task 3: Incremental transactional transformation service

**Files:**
- Create: `src/govinsight/transform/repositories.py`
- Create: `src/govinsight/transform/service.py`
- Modify: `src/govinsight/transform/__init__.py`
- Create: `tests/integration/test_silver_service.py`

**Interfaces:**
- Consumes: `parse_procurement`, Silver tables, Bronze `raw_api_response`, control `etl_watermark`.
- Produces: `SilverTransformationService.transform_pending(limit: int = 100) -> TransformationResult`.
- Produces: counters `responses_processed`, `records_received`, `inserted`, `updated`, `unchanged`,
  `rejected` and `last_raw_response_id`.

- [x] **Step 1: Write one end-to-end failing integration test**

Insert real Bronze response A containing one valid fixture record plus one invalid record. Execute
the service and assert one procurement, one quarantine, safe codes, exact lineage and watermark A.
Replay with the same watermark and assert zero writes. Insert response B for the same natural key
with a newer `dataAtualizacaoGlobal` and changed object, then assert one update and lineage B. Add
response C with an older update time and assert the newer Silver state does not regress.

Finally force a repository exception while processing another response and assert Silver writes
and watermark advancement both roll back.

- [x] **Step 2: Run RED**

Run: `pytest tests/integration/test_silver_service.py -v -p no:cacheprovider`

Expected: collection fails because the repositories and service do not exist.

- [x] **Step 3: Implement repositories**

Required method signatures:

- `BronzeProcurementRepository.pending(connection: Connection, after_id: int, limit: int) ->
  list[Mapping[str, Any]]`;
- `ProcurementRepository.upsert(connection: Connection, value: NormalizedProcurement) ->
  WriteOutcome`;
- `RejectedRecordRepository.insert(connection: Connection, value: RejectedProcurement) -> bool`;
- `SilverWatermarkRepository.current(connection: Connection) -> int`;
- `SilverWatermarkRepository.advance(connection: Connection, raw_response_id: int) -> None`.

The procurement `ON CONFLICT` update condition is:

```text
excluded.data_atualizacao_global > current.data_atualizacao_global
OR (timestamps equal AND excluded.source_raw_response_id > current.source_raw_response_id)
```

Return `inserted`, `updated` or `unchanged` from deterministic SQL results. Quarantine uses conflict
do nothing on the source-record unique constraint. Watermark uses the fixed key from the spec and
never moves backward.

- [x] **Step 4: Implement service transaction flow**

For each pending Bronze row, open `engine.begin()`, lock/read the watermark, re-check that the RAW
id is still pending, decode `raw_body`, require an object with list-valued `data`, parse every
record, write valid/quarantined results and advance the watermark. Envelope errors raise a safe
`SilverEnvelopeError(raw_response_id, code)` with no payload. Return frozen measured counters.

- [x] **Step 5: Run GREEN**

Run: `pytest tests/integration/test_silver_service.py -v -p no:cacheprovider`

Run: `pytest tests/unit/transform/test_procurement.py tests/integration/test_silver_migration.py tests/integration/test_silver_service.py -v -p no:cacheprovider`

Expected: focused Silver suite passes.

- [x] **Step 6: Commit**

```powershell
git add src/govinsight/transform tests/integration/test_silver_service.py
git commit -m "feat: add incremental silver transformation"
```

---

### Task 4: Documentation and Phase 4 gate

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-4.md`
- Modify: `docs/superpowers/plans/2026-08-23-phase-4-silver-transformation.md`

**Interfaces:**
- Consumes: fresh output from every Phase 4 gate.
- Produces: reproducible Silver usage and truthful `STAGE_STATUS`.

- [x] **Step 1: Document one bounded Silver execution**

Add README commands for migration and `SilverTransformationService(engine).transform_pending()`.
Explain Bronze lineage, current-state semantics, quarantine, watermark and exclusions.

- [x] **Step 2: Run final gates once**

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m pytest -m "not integration" -p no:cacheprovider --cov=govinsight --cov-report=term-missing
```

With real PostgreSQL:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_postgres.py tests/integration/test_raw_migration.py tests/integration/test_raw_repositories.py tests/integration/test_raw_service.py tests/integration/test_silver_migration.py tests/integration/test_silver_service.py -v -p no:cacheprovider
.\.venv\Scripts\python.exe -m alembic current
```

Expected: lint/format clean, coverage at least 80%, all local/PostgreSQL tests pass and Alembic is
`20260823_0003 (head)`. Do not rerun the live PNCP test because Phase 4 consumes local Bronze data.

- [x] **Step 3: Perform a compact BUG HUNT**

Inspect only null money, naive timestamps, invalid sibling isolation, replay, older-source
regression, transaction rollback, payload leakage and watermark mutation. Any real defect gets one
focused regression before correction.

- [x] **Step 4: Write measured checkpoint and close plan**

Record files, test counts, coverage, Bronze responses transformed, inserted/updated/unchanged/
rejected counts, problems, corrections, risks and Phase 5. Mark checkboxes only after evidence.

- [x] **Step 5: Verify and commit**

Run `git diff --check`, anchored unchecked-checkbox search and `git status --short`.

```powershell
git add README.md docs/checkpoints/phase-4.md docs/superpowers/plans/2026-08-23-phase-4-silver-transformation.md
git commit -m "docs: add silver transformation guide and checkpoint"
```
