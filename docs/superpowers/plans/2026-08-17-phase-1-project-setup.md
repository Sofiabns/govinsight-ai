# Phase 1 Project Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reproducible GovInsight AI foundation that starts through Docker Compose, connects FastAPI to PostgreSQL, emits structured logs, and passes unit and integration gates.

**Architecture:** The repository uses a `src/govinsight` Python package, Pydantic Settings as the single configuration boundary, SQLAlchemy/psycopg for PostgreSQL, Structlog for JSON logs, and FastAPI for the first health endpoint. Docker Compose owns the reproducible runtime; PostgreSQL schemas are versioned with Alembic.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy 2, psycopg 3, Structlog, Alembic, pytest, Ruff, PostgreSQL 16, Docker Compose.

## Global Constraints

- Use Python `>=3.12,<3.14`; the container image is `python:3.12-slim`.
- PostgreSQL is the only application database.
- Never commit `.env`, credentials, caches, virtual environments, coverage files, or database volumes.
- Runtime configuration comes from environment variables prefixed with `GOVINSIGHT_`.
- Application logs are structured JSON and must never include database passwords.
- Production behavior must be written test-first and observed failing before implementation.
- This phase creates setup, connectivity, health, logging, and schemas only; PNCP extraction belongs to Phase 2.
- Work on branch `feat/phase-1-project-setup`; do not implement on `main`.

---

### Task 1: Repository and dependency foundation

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `README.md`
- Create: `src/govinsight/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Consumes: approved Fase 0 discovery.
- Produces: installable package `govinsight`, pytest/Ruff configuration, documented environment contract.

- [ ] **Step 1: Initialize Git on the feature branch**

Run: `git init -b feat/phase-1-project-setup`

Expected: repository initialized with `feat/phase-1-project-setup` as the unborn branch.

- [ ] **Step 2: Create dependency metadata**

Use these direct runtime dependencies in `pyproject.toml`: `alembic`, `fastapi`, `pydantic-settings`, `psycopg[binary]`, `sqlalchemy`, `structlog`, and `uvicorn[standard]`. Use `pytest`, `pytest-cov`, and `ruff` in the `dev` optional group. Configure setuptools package discovery under `src`, pytest paths/markers, coverage for `govinsight`, and Ruff target `py312`.

`requirements.txt` contains `-e .`; `requirements-dev.txt` contains `-e .[dev]`.

- [ ] **Step 3: Create safe environment templates**

`.env.example` defines non-secret local defaults for app environment, log level, PostgreSQL database, application user, password placeholder, host, port, and pool settings. `.gitignore` excludes `.env`, `.venv`, caches, coverage, build outputs, IDE settings, `data/`, and `.worktrees/`.

- [ ] **Step 4: Install the development environment**

Run:

```powershell
& 'C:\Users\Sofia\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-dev.txt
```

Expected: installation exits 0 and `python -c "import govinsight"` exits 0.

- [ ] **Step 5: Commit the foundation**

Run:

```powershell
git add .gitignore .env.example pyproject.toml requirements.txt requirements-dev.txt README.md src/govinsight/__init__.py tests/__init__.py
git commit -m "chore: initialize project structure"
```

Expected: one focused root commit.

### Task 2: Typed settings contract

**Files:**
- Create: `tests/unit/test_config.py`
- Create: `src/govinsight/config.py`

**Interfaces:**
- Consumes: environment variables prefixed with `GOVINSIGHT_`.
- Produces: `Settings`, `get_settings()`, and `Settings.database_url: str`.

- [ ] **Step 1: Write the failing settings tests**

```python
from govinsight.config import Settings


def test_database_url_percent_encodes_credentials() -> None:
    settings = Settings(
        postgres_user="user@example.com",
        postgres_password="p@ss/word",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="govinsight",
    )
    assert settings.database_url == (
        "postgresql+psycopg://user%40example.com:p%40ss%2Fword@db:5432/govinsight"
    )


def test_settings_reject_non_positive_pool_size() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(postgres_pool_size=0)
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/unit/test_config.py -v`

Expected: collection fails because `govinsight.config` does not exist.

- [ ] **Step 3: Implement the minimal settings boundary**

Implement `Settings` with `SettingsConfigDict(env_prefix="GOVINSIGHT_", env_file=".env", extra="ignore")`, `SecretStr` for the password, bounded positive pool fields, and a URL assembled with `sqlalchemy.engine.URL.create(...).render_as_string(hide_password=False)`. Cache `get_settings()` with `functools.lru_cache`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/unit/test_config.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

Run: `git add src/govinsight/config.py tests/unit/test_config.py && git commit -m "feat: add typed application settings"`

### Task 3: Structured logging

**Files:**
- Create: `tests/unit/test_logging.py`
- Create: `src/govinsight/observability/__init__.py`
- Create: `src/govinsight/observability/logging.py`

**Interfaces:**
- Consumes: `log_level` from `Settings`.
- Produces: `configure_logging(log_level: str) -> None` and `get_logger(name: str)`.

- [ ] **Step 1: Write the failing behavior test**

Use `capsys`, call `configure_logging("INFO")`, emit `logger.info("pipeline_started", pipeline="setup", stage="health", records_processed=0)`, parse the captured line with `json.loads`, and assert literal values for `event`, `pipeline`, `stage`, `records_processed`, and presence of an ISO timestamp.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/unit/test_logging.py -v`

Expected: collection fails because the logging module does not exist.

- [ ] **Step 3: Implement JSON logging**

Configure stdlib logging plus Structlog processors for log level, ISO UTC timestamp, stack information, exception formatting, and `JSONRenderer`. Return a bound logger from `get_logger`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/unit/test_logging.py -v`

Expected: 1 passed and no warnings.

- [ ] **Step 5: Commit**

Run: `git add src/govinsight/observability tests/unit/test_logging.py && git commit -m "feat: add structured application logging"`

### Task 4: Database engine and connectivity

**Files:**
- Create: `tests/unit/test_database.py`
- Create: `tests/integration/test_postgres.py`
- Create: `src/govinsight/database/__init__.py`
- Create: `src/govinsight/database/session.py`

**Interfaces:**
- Consumes: `Settings.database_url`, pool size and overflow.
- Produces: `create_database_engine(settings: Settings) -> Engine` and `check_database(engine: Engine) -> bool`.

- [ ] **Step 1: Write the failing unit test**

Create a SQLite in-memory engine, call `check_database(engine)`, and assert `True`. This catches a missing or invalid `SELECT 1` implementation without mocking SQLAlchemy.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/unit/test_database.py -v`

Expected: collection fails because `govinsight.database.session` does not exist.

- [ ] **Step 3: Implement minimal database functions**

`create_database_engine` calls `create_engine(settings.database_url, pool_pre_ping=True, pool_size=settings.postgres_pool_size, max_overflow=settings.postgres_max_overflow)`. `check_database` opens a connection and returns whether `connection.execute(text("SELECT 1")).scalar_one() == 1`.

- [ ] **Step 4: Verify unit GREEN**

Run: `pytest tests/unit/test_database.py -v`

Expected: 1 passed.

- [ ] **Step 5: Add the integration contract**

The integration test reads `GOVINSIGHT_DATABASE_URL`; if absent it skips with a precise reason. When present, it creates an engine from that URL and asserts `check_database(engine) is True`, disposing the engine afterward.

- [ ] **Step 6: Commit**

Run: `git add src/govinsight/database tests/unit/test_database.py tests/integration/test_postgres.py && git commit -m "feat: add database connectivity boundary"`

### Task 5: FastAPI readiness endpoint

**Files:**
- Create: `tests/unit/test_health_api.py`
- Create: `src/govinsight/api/__init__.py`
- Create: `src/govinsight/api/main.py`

**Interfaces:**
- Consumes: `check_database` through `app.state.database_engine`.
- Produces: ASGI `app` and `GET /health` returning `200` when PostgreSQL is ready or `503` when it is unavailable.

- [ ] **Step 1: Write failing API tests**

Use `TestClient`. Supply an app factory dependency that returns `True` and assert literal JSON `{"status": "ok", "database": "reachable"}` with 200. Supply one returning `False` and assert `{"detail": {"status": "unavailable", "database": "unreachable"}}` with 503.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/unit/test_health_api.py -v`

Expected: collection fails because the API module does not exist.

- [ ] **Step 3: Implement the app factory**

Implement `create_app(database_check: Callable[[], bool] | None = None) -> FastAPI`. Configure logging, create/dispose the database engine through lifespan when no check is injected, and implement `/health` with the exact response contracts above. Export `app = create_app()`.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/unit/test_health_api.py -v`

Expected: 2 passed.

- [ ] **Step 5: Commit**

Run: `git add src/govinsight/api tests/unit/test_health_api.py && git commit -m "feat: add database-aware health endpoint"`

### Task 6: Alembic and container runtime

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260817_0001_create_data_schemas.py`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: environment settings and the package created earlier.
- Produces: PostgreSQL 16 service, API service, and versioned schemas `bronze`, `silver`, `gold`, `control`.

- [ ] **Step 1: Create an initial migration**

The upgrade executes `CREATE SCHEMA IF NOT EXISTS` for `bronze`, `silver`, `gold`, and `control`. The downgrade drops only these empty schemas in reverse order. Alembic reads the SQLAlchemy URL from `Settings`, not a committed credential.

- [ ] **Step 2: Create the non-root API image**

Use `python:3.12-slim`, install `requirements.txt`, copy the package and migrations, create an unprivileged `app` user, expose port 8000, and run `uvicorn govinsight.api.main:app --host 0.0.0.0 --port 8000`.

- [ ] **Step 3: Create Compose services**

PostgreSQL 16 uses a named volume and `pg_isready`. API waits for a healthy database, receives `GOVINSIGHT_POSTGRES_HOST=postgres`, runs `alembic upgrade head` before Uvicorn, and has an HTTP healthcheck. Use `${VARIABLE:-default}` interpolation so `docker compose up` works without a secret file while `.env.example` documents overrides.

- [ ] **Step 4: Validate configuration statically**

Run: `docker compose config --quiet`

Expected: exit 0.

- [ ] **Step 5: Start and verify the stack**

Run:

```powershell
docker compose up -d --build
docker compose ps
docker compose exec -T api pytest -m "not integration" -v
$env:GOVINSIGHT_DATABASE_URL='postgresql+psycopg://govinsight_app:govinsight_local@localhost:5432/govinsight'; pytest tests/integration/test_postgres.py -v
Invoke-RestMethod http://localhost:8000/health
```

Expected: both services healthy, unit suite passes, integration test passes, and health returns `status=ok` and `database=reachable`.

- [ ] **Step 6: Inspect database schemas**

Run: `docker compose exec -T postgres psql -U govinsight_app -d govinsight -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('bronze','silver','gold','control') ORDER BY schema_name;"`

Expected: exactly four rows.

- [ ] **Step 7: Commit**

Run: `git add alembic.ini alembic Dockerfile docker-compose.yml .dockerignore && git commit -m "feat: add reproducible postgres application stack"`

### Task 7: Phase gate and documentation

**Files:**
- Modify: `README.md`
- Create: `docs/checkpoints/phase-1.md`

**Interfaces:**
- Consumes: verified command output from Tasks 1–6.
- Produces: reproducible setup instructions and factual Fase 1 checkpoint.

- [ ] **Step 1: Run full quality verification**

Run:

```powershell
ruff check .
ruff format --check .
pytest -v --cov=govinsight --cov-report=term-missing
docker compose config --quiet
docker compose ps
Invoke-RestMethod http://localhost:8000/health
```

Expected: zero lint/format errors, all tests pass, Compose validates, services are healthy, and health reports database reachable.

- [ ] **Step 2: Document only observed results**

README covers prerequisites, local install, Docker startup, tests, configuration, architecture scope, and current limitations. `docs/checkpoints/phase-1.md` records exact test counts, failures, service status, problems, corrections, and remaining risks from the fresh verification output.

- [ ] **Step 3: Commit docs**

Run: `git add README.md docs/checkpoints/phase-1.md && git commit -m "docs: add phase one setup and verification guide"`

- [ ] **Step 4: Confirm clean status and history**

Run: `git status --short; git log --oneline --decorate -10`

Expected: clean worktree and focused professional commits on `feat/phase-1-project-setup`.
