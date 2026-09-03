# Phase 16 — Final QA and bug hunt

## Verified on 2026-09-03

- Ruff lint and formatting: passed.
- Automated suite with PostgreSQL: 147 passed, 1 live test intentionally excluded.
- Measured test coverage: 90.36% (required minimum: 80%).
- Production Docker image: built successfully from repository files.
- Alembic migrations: applied successfully during container startup.
- PostgreSQL and FastAPI container health checks: healthy.
- `GET /health`: 200 with reachable database.
- `GET /dashboard/`: 200 with packaged dashboard assets.
- `POST /agent/report`: executed against the real Gold analytics view.
- Official Compras.gov fallback import: 4,507 valid records loaded through Bronze, Silver and Gold.
- Loaded analytical totals: BRL 317,092,692,183.2131 estimated and BRL 5,995,086,289.1422 homologated.

The local port 8000 was already occupied outside Compose, so the final runtime probe used the
documented `API_PORT` override with port 8010. This does not affect the default configuration.

## Bug hunt fixes

- Enabled pytest import isolation for duplicate test filenames in different domains.
- Changed CI to run PostgreSQL integration tests so its 80% coverage gate is attainable and honest.
- Included dashboard assets explicitly in the production Python wheel.
- Blocked executive agent reports when the Gold procurement count is zero.
