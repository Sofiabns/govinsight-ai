# GovInsight AI Portfolio Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a recruiter-ready GovInsight AI demo with visible natural-language analytics, optional OpenAI planning, managed PostgreSQL and professional GitHub presentation.

**Architecture:** Deploy the existing FastAPI application and static dashboard as one Vercel project connected to pooled Neon PostgreSQL. Keep data ingestion in a separate GitHub Actions workflow and convert LLM output into a typed query plan before deterministic SQL compilation and the existing read-only guard.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, PostgreSQL/Neon, OpenAI Responses API, vanilla HTML/CSS/JavaScript, Docker, GitHub Actions, Vercel.

**Spec:** `docs/superpowers/specs/2026-09-03-portfolio-production-design.md`

## Global Constraints

- Preserve Python `>=3.12,<3.14` and the existing package layout.
- Use official procurement data only; never commit downloaded CSV or database files.
- The LLM must never emit executable SQL or receive database credentials.
- All analytical execution remains one parameterized, read-only, allow-listed statement with `LIMIT <= 200` and a five-second database timeout.
- The deterministic agent remains the no-key default and runtime fallback.
- Do not claim nationwide coverage, causal inference or fraud detection.
- Keep the dashboard framework-free and same-origin with the API.
- Do not publish, push, create cloud resources or spend money until Sofia explicitly authorizes those external actions.

---

### Task 1: Introduce a typed query-plan boundary

**Files:**
- Create: `src/govinsight/agents/query_plan.py`
- Modify: `src/govinsight/agents/data_agent.py`
- Modify: `src/govinsight/agents/__init__.py`
- Test: `tests/unit/agents/test_query_plan.py`

**Interfaces:**
- Consumes: `AnalyticsFilters`, `Measure`, `RankDimension`, `GeneratedQuery`.
- Produces: `QueryIntent`, `QueryPlan`, `QueryPlanCompiler.compile(plan: QueryPlan) -> GeneratedQuery`.

- [ ] **Step 1: Write failing schema tests** covering valid summary/ranking/trend plans and rejection of reversed dates, invalid UF, `limit > 100` and a ranking without a dimension.
- [ ] **Step 2: Run** `python -m pytest tests/unit/agents/test_query_plan.py -v` and confirm failures are caused by missing plan types.
- [ ] **Step 3: Implement** frozen Pydantic enums/models and cross-field validation matching the exact JSON contract in the spec.
- [ ] **Step 4: Write failing compiler tests** asserting parameterized filters, correct approved Gold view, stable ordering and bounded limits for every intent.
- [ ] **Step 5: Implement** `QueryPlanCompiler` with fixed SQL templates and named parameters; do not interpolate user values or identifiers.
- [ ] **Step 6: Refactor** `RuleBasedSQLGenerator` to create a `QueryPlan` and compile it, preserving its existing public behavior and safety guard.
- [ ] **Step 7: Run** the new tests plus `tests/unit/agents/test_data_agent.py`; then run Ruff on the changed files.
- [ ] **Step 8: Commit** with `feat: add typed analytical query plans`.

### Task 2: Add the optional OpenAI query planner

**Files:**
- Create: `src/govinsight/agents/openai_planner.py`
- Modify: `src/govinsight/config.py`
- Modify: `src/govinsight/api/main.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/unit/agents/test_openai_planner.py`

**Interfaces:**
- Consumes: `QueryPlan`, `QueryPlanCompiler`, OpenAI Responses API.
- Produces: `OpenAIQueryPlanner.plan(question: str) -> QueryPlan` and `FallbackQueryPlanner.plan(question: str) -> QueryPlan`.

- [ ] **Step 1: Write failing configuration tests** for provider values `rules|openai`, missing key/model rejection when OpenAI is selected and secret-safe representations.
- [ ] **Step 2: Add** settings `agent_provider`, `openai_api_key`, `openai_model`, `openai_timeout_seconds=12` and `agent_fallback_enabled=True`; add `openai>=2,<3` to project dependencies.
- [ ] **Step 3: Write failing planner tests** with a fake OpenAI client for valid Structured Output, malformed output, timeout, unsupported question and prompt injection.
- [ ] **Step 4: Implement** a Responses API request whose JSON Schema is generated from `QueryPlan`; set storage off, bound output size and pass only the question plus approved metric catalog.
- [ ] **Step 5: Implement** fallback to the deterministic planner for timeout/transport/invalid-schema failures; log provider, duration and outcome only.
- [ ] **Step 6: Wire** the selected planner in FastAPI lifespan without changing the SQL executor or critic gate.
- [ ] **Step 7: Run** focused planner, agent and API tests plus Ruff; verify logs never contain API keys or the full user prompt.
- [ ] **Step 8: Commit** with `feat: add optional structured OpenAI planner`.

### Task 3: Strengthen agent evaluation and runtime protection

**Files:**
- Modify: `tests/fixtures/agents/agent_evaluation.json`
- Modify: `src/govinsight/agents/evaluation.py`
- Modify: `src/govinsight/api/main.py`
- Create: `src/govinsight/api/rate_limit.py`
- Test: `tests/unit/agents/test_evaluation.py`
- Test: `tests/unit/api/test_agent_api.py`

**Interfaces:**
- Consumes: `/agent/query`, `/agent/report`, `QueryPlan`, `ExecutiveReport`.
- Produces: benchmark metrics by intent/filter/safety class and a bounded request guard.

- [ ] **Step 1: Expand the benchmark** to at least 30 cases: five intents, three dimensions, date/UF filters, insufficient-data cases, unsupported supplier/category requests and ten adversarial prompts.
- [ ] **Step 2: Write failing evaluator tests** for intent accuracy, filter accuracy, grounded answer rate, safe-refusal rate and unexpected failure rate.
- [ ] **Step 3: Extend the evaluator** without weakening existing metrics; store per-case status and aggregate counts, never model reasoning text.
- [ ] **Step 4: Write failing API protection tests** for 500-character limits, malformed JSON, timeout mapping, repeated requests and safe 422/429/503 responses.
- [ ] **Step 5: Implement** a small fixed-window limiter for the AI routes and preserve the platform firewall as the production outer boundary.
- [ ] **Step 6: Run** the benchmark for both rules and mocked-OpenAI modes; require 100% grounding and prompt-injection blocking on the versioned set.
- [ ] **Step 7: Commit** with `test: expand agent safety evaluation`.

### Task 4: Put “Pergunte aos dados” in the dashboard

**Files:**
- Modify: `src/govinsight/api/dashboard/index.html`
- Modify: `src/govinsight/api/dashboard/styles.css`
- Modify: `src/govinsight/api/dashboard/app.js`
- Test: `tests/unit/api/test_dashboard.py`

**Interfaces:**
- Consumes: `POST /agent/report` with `{ "question": string }`.
- Produces: accessible question form, preset prompts, report cards and evidence disclosure.

- [ ] **Step 1: Extend the dashboard route test** to assert the question form, four example prompts, result region and evidence control exist.
- [ ] **Step 2: Add semantic HTML** for the agent section beneath KPIs and above analytical panels, keeping the current editorial visual language.
- [ ] **Step 3: Add responsive CSS** for prompt chips, loading skeleton, executive report, metric tiles, attention callout and collapsible evidence.
- [ ] **Step 4: Add client behavior** with `AbortController`, disabled submission, 15-second timeout, safe text rendering through `textContent`, empty/error messages and no HTML injection from responses.
- [ ] **Step 5: Connect** example prompts and free-text input to `/agent/report`; show source, row count and SQL only inside the evidence disclosure.
- [ ] **Step 6: Verify** desktop and mobile keyboard flow once; run the focused dashboard/API tests and Ruff for Python files.
- [ ] **Step 7: Commit** with `feat: add natural-language analytics experience`.

### Task 5: Make the application serverless-production ready

**Files:**
- Create: `app.py`
- Modify: `src/govinsight/config.py`
- Modify: `src/govinsight/database/session.py`
- Modify: `src/govinsight/api/main.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/api/test_lifespan.py`

**Interfaces:**
- Consumes: pooled read-only `GOVINSIGHT_DATABASE_DSN`; direct writer DSN only outside the web runtime.
- Produces: root `app` entrypoint and serverless-safe engine lifecycle.

- [ ] **Step 1: Write failing settings tests** for a complete DSN override, SSL requirement in production and redacted secret output.
- [ ] **Step 2: Implement** optional `GOVINSIGHT_DATABASE_DSN` as `SecretStr`; retain component settings for Docker local development.
- [ ] **Step 3: Write failing lifecycle tests** showing that migrations/ingestion never run during import or request startup and engine disposal remains safe.
- [ ] **Step 4: Tune** SQLAlchemy for serverless pooled connections: bounded pool, pre-ping and recycle settings controlled by existing configuration.
- [ ] **Step 5: Add** root `app.py` containing only `from govinsight.api.main import app` for Vercel discovery.
- [ ] **Step 6: Add** `[tool.vercel] entrypoint = "app:app"` only if the Vercel build probe does not discover the root entrypoint automatically.
- [ ] **Step 7: Run** unit/API tests, build the Python wheel and confirm dashboard assets exist inside it.
- [ ] **Step 8: Commit** with `feat: prepare FastAPI for Vercel and Neon`.

### Task 6: Automate managed database bootstrap and refresh

**Files:**
- Create: `.github/workflows/load-demo-data.yml`
- Create: `scripts/download_demo_data.ps1`
- Modify: `src/govinsight/importers/pncp_csv.py`
- Modify: `README.md`
- Test: `tests/unit/importers/test_pncp_csv.py`

**Interfaces:**
- Consumes: official Compras.gov CSV URL and GitHub secret `GOVINSIGHT_DATABASE_ADMIN_DSN`.
- Produces: idempotent Neon migration/import/quality/reconciliation workflow with a summary artifact.

- [ ] **Step 1: Write failing importer tests** for streaming row limits, truncated final CSV rows, duplicate replay and source metadata.
- [ ] **Step 2: Refactor** CSV parsing to stream and stop after the requested valid-record limit instead of materializing the full export.
- [ ] **Step 3: Implement** a downloader that requests a bounded byte range, checks HTTP 200/206, records ETag/Last-Modified and rejects HTML/error payloads.
- [ ] **Step 4: Add a manual workflow** with `workflow_dispatch`, Python 3.12, secret preflight, Alembic upgrade, download, 5,000-row import, quality check and aggregate summary.
- [ ] **Step 5: Use** direct administrative DSN only in this workflow; create or grant a separate read-only runtime role and output no credential-bearing URLs.
- [ ] **Step 6: Run** the workflow first against a disposable Neon branch; confirm a second execution is idempotent before enabling a weekly schedule.
- [ ] **Step 7: Document** dataset origin, federal scope, retrieval date, record count, period and refresh behavior.
- [ ] **Step 8: Commit** with `ci: automate official demo data refresh`.

### Task 7: Upgrade CI, dependency security and reproducibility

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Create: `requirements.lock`
- Modify: `requirements-dev.txt`
- Modify: `README.md`

**Interfaces:**
- Consumes: project dependency metadata and PostgreSQL service.
- Produces: reproducible install, dependency audit, CI badge source and deploy gate.

- [ ] **Step 1: Generate** `requirements.lock` from Python 3.12 with hashes or exact transitive versions and document the regeneration command.
- [ ] **Step 2: Change CI** to install the lock, run Ruff, formatting, all non-live tests, 80% coverage gate, agent benchmark, dependency audit and Docker build.
- [ ] **Step 3: Configure Dependabot** weekly for `pip` and `github-actions`, grouping patch/minor updates separately from majors.
- [ ] **Step 4: Add** workflow concurrency cancellation and least-privilege permissions; keep external live tests manual.
- [ ] **Step 5: Run** the full CI command locally once and verify the lock installs into a clean temporary environment.
- [ ] **Step 6: Commit** with `ci: add reproducibility and dependency security`.

### Task 8: Rebuild the README and visual portfolio assets

**Files:**
- Modify: `README.md`
- Create: `docs/images/govinsight-dashboard.png`
- Create: `docs/images/govinsight-social-preview.png`
- Create: `LICENSE`
- Modify: `docs/architecture.md`
- Modify: `docs/agents.md`

**Interfaces:**
- Consumes: verified production metrics and public URLs.
- Produces: five-second recruiter overview, deep technical path and reusable GitHub preview assets.

- [ ] **Step 1: Rewrite the README opening** as value proposition, truthful status, screenshot, demo/API/docs links, and verified metrics before any setup detail.
- [ ] **Step 2: Move long operational explanations** into existing docs and retain a Docker quickstart that reaches a visible result with the fewest commands.
- [ ] **Step 3: Add** architecture Mermaid, core decisions/trade-offs, agent safety, evaluation methodology, data scope, limitations and interview-ready talking points.
- [ ] **Step 4: Capture** the real populated dashboard at desktop width and create a legible 1280×640 social-preview crop without fabricated statistics.
- [ ] **Step 5: Add** an MIT license naming Sofia and a concise authorship/contact section using only information she has provided.
- [ ] **Step 6: Add** CI and license badges only after their target URLs exist; validate every relative and public link.
- [ ] **Step 7: Review** the rendered README on desktop and mobile and confirm the first screen answers what, why, proof and demo.
- [ ] **Step 8: Commit** with `docs: polish recruiter-facing project presentation`.

### Task 9: Publish GitHub, Neon and Vercel production

**Files:**
- Modify if required by deployment probe: `app.py`, `pyproject.toml`, `.env.example`, `README.md`
- Create after verification: `docs/checkpoints/production-release.md`

**Interfaces:**
- Consumes: authorized GitHub account, Neon project, Vercel project and optional OpenAI key/model.
- Produces: public repository, live demo URL, protected secrets and `v1.0.0` release.

- [ ] **Step 1: Rename or merge** the completed feature history into local `main`; preserve all existing commits and never force-push.
- [ ] **Step 2: Create the GitHub repository** only after Sofia authorizes publication; push `main` and confirm CI passes remotely.
- [ ] **Step 3: Set repository metadata**: description, homepage, topics, social preview and default-branch protection after checking actual GitHub capabilities.
- [ ] **Step 4: Create Neon resources** with a writer/admin role for workflows and a least-privilege read-only runtime role; store pooled and direct DSNs in the correct secret stores.
- [ ] **Step 5: Run** the manual demo-data workflow, verify 4,507+ Gold records and confirm analytics totals directly in production.
- [ ] **Step 6: Import the GitHub repository into Vercel**, configure production environment variables and deploy the FastAPI app.
- [ ] **Step 7: Execute smoke tests** for health, dashboard, all analytics endpoints, rules-based report, OpenAI report when enabled, evidence and empty/error states.
- [ ] **Step 8: Update README links**, capture final production screenshots, tag `v1.0.0` and create release notes only after all smoke checks pass.
- [ ] **Step 9: Pin GovInsight AI** in the appropriate position on Sofia's GitHub profile after reviewing her other public repositories.
- [ ] **Step 10: Commit** final URL/documentation changes with `release: publish GovInsight AI v1.0.0`.

## Recommended execution order

1. Tasks 1–3 establish the safe AI contract and evaluation gate.
2. Task 4 exposes the product's differentiating feature to recruiters.
3. Tasks 5–7 make deployment, data and CI reproducible.
4. Task 8 packages the evidence for recruiter scanning.
5. Task 9 performs external publication only with explicit authorization.

## Completion evidence

- Public dashboard URL and API documentation URL.
- Populated managed database with documented official sample scope.
- Successful CI run, production smoke report and agent benchmark artifact.
- Screenshot/social preview, concise README, license, topics and `v1.0.0` release.
- No secrets, downloaded datasets or database dumps in Git history.
