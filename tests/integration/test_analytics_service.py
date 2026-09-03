import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from structlog.testing import capture_logs

from govinsight.analytics.models import AnalyticsFilters, Measure, RankDimension
from govinsight.analytics.service import AnalyticsService
from govinsight.raw.tables import etl_run, raw_api_response
from govinsight.warehouse.tables import (
    dim_date,
    dim_modality,
    dim_organization,
    dim_unit,
    fact_procurement,
)


@pytest.fixture(scope="module")
def engine() -> Engine:
    database_url = os.getenv("GOVINSIGHT_DATABASE_URL")
    if database_url is None:
        pytest.skip("GOVINSIGHT_DATABASE_URL is required for analytics integration tests")
    value = create_engine(database_url, pool_pre_ping=True)
    try:
        yield value
    finally:
        value.dispose()


@pytest.fixture
def analytics_sample(engine: Engine) -> dict[str, object]:
    token = uuid4().hex
    number = int(token[:12], 16)
    cnpj_a = f"{number % 10**14:014d}"
    cnpj_b = f"{(number + 1) % 10**14:014d}"
    now = datetime.now(UTC)
    run_id = uuid4()
    dates = [
        date(2040, 1, 1),
        date(2040, 2, 1),
        date(2040, 4, 1),
        date(2040, 5, 1),
        date(2040, 6, 1),
    ]
    pncp_keys = [f"ANALYTICS-{token}-{index}" for index in range(1, 8)]

    with engine.begin() as connection:
        baseline_summary = (
            connection.execute(sa.text("SELECT * FROM gold.analytics_summary")).mappings().one()
        )
        connection.execute(
            etl_run.insert().values(
                id=run_id,
                pipeline_name=f"analytics-test-{token}",
                dataset="procurements",
                mode="publicacao",
                status="RUNNING",
                started_at=now,
            )
        )
        raw_id = connection.execute(
            raw_api_response.insert()
            .values(
                etl_run_id=run_id,
                source="pncp",
                dataset="procurements",
                endpoint=f"/analytics-test/{token}",
                request_params={},
                request_fingerprint=token.ljust(64, "0"),
                window_start=dates[0],
                window_end=dates[-1],
                page_number=1,
                http_status=200,
                raw_body="{}",
                body_sha256=token.ljust(64, "a"),
                record_count=7,
                collected_at=now,
                duration_ms=1,
            )
            .returning(raw_api_response.c.id)
        ).scalar_one()
        connection.execute(
            dim_date.insert(),
            [
                {
                    "date_key": int(value.strftime("%Y%m%d")),
                    "full_date": value,
                    "day": value.day,
                    "month": value.month,
                    "quarter": (value.month - 1) // 3 + 1,
                    "year": value.year,
                    "iso_weekday": value.isoweekday(),
                }
                for value in dates
            ],
        )
        organization_keys = connection.execute(
            dim_organization.insert()
            .values(
                [
                    {
                        "orgao_cnpj": cnpj_a,
                        "orgao_razao_social": "Órgão Analytics A",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "orgao_cnpj": cnpj_b,
                        "orgao_razao_social": "Órgão Analytics B",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
            .returning(dim_organization.c.organization_key, dim_organization.c.orgao_cnpj)
        ).all()
        organizations = {row.orgao_cnpj: row.organization_key for row in organization_keys}
        unit_keys = connection.execute(
            dim_unit.insert()
            .values(
                [
                    {
                        "orgao_cnpj": cnpj_a,
                        "codigo_unidade": f"SP-{token}",
                        "nome_unidade": "Unidade SP",
                        "uf_sigla": "ZZ",
                        "uf_nome": "Acre",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "orgao_cnpj": cnpj_a,
                        "codigo_unidade": f"SP2-{token}",
                        "nome_unidade": "Unidade SP 2",
                        "uf_sigla": "ZZ",
                        "uf_nome": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "orgao_cnpj": cnpj_b,
                        "codigo_unidade": f"RJ-{token}",
                        "nome_unidade": "Unidade RJ",
                        "uf_sigla": "RJ",
                        "uf_nome": "Rio de Janeiro",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "orgao_cnpj": cnpj_b,
                        "codigo_unidade": f"UK-{token}",
                        "nome_unidade": "Unidade sem UF",
                        "uf_sigla": None,
                        "uf_nome": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
            .returning(dim_unit.c.unit_key, dim_unit.c.codigo_unidade)
        ).all()
        units = {row.codigo_unidade: row.unit_key for row in unit_keys}
        modality_ids = [800000 + number % 100000, 900000 + number % 100000]
        modality_keys = connection.execute(
            dim_modality.insert()
            .values(
                [
                    {
                        "modalidade_id": modality_ids[0],
                        "modalidade_nome": "Modalidade A",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "modalidade_id": modality_ids[1],
                        "modalidade_nome": "Modalidade B",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
            .returning(dim_modality.c.modality_key, dim_modality.c.modalidade_id)
        ).all()
        modalities = {row.modalidade_id: row.modality_key for row in modality_keys}
        facts = [
            (cnpj_a, f"SP-{token}", modality_ids[0], dates[0], "100", "10"),
            (cnpj_b, f"RJ-{token}", modality_ids[1], dates[0], "200", "20"),
            (cnpj_a, f"SP2-{token}", modality_ids[0], dates[1], "300", "30"),
            (cnpj_a, f"SP-{token}", modality_ids[1], dates[1], None, "40"),
            (cnpj_b, f"UK-{token}", modality_ids[1], dates[2], "500", "1000"),
            (cnpj_a, f"SP-{token}", modality_ids[0], dates[3], None, "0"),
            (cnpj_a, f"SP-{token}", modality_ids[0], dates[4], None, "50"),
        ]
        connection.execute(
            fact_procurement.insert(),
            [
                {
                    "numero_controle_pncp": pncp_keys[index],
                    "organization_key": organizations[item[0]],
                    "unit_key": units[item[1]],
                    "modality_key": modalities[item[2]],
                    "publication_date_key": int(item[3].strftime("%Y%m%d")),
                    "source_raw_response_id": raw_id,
                    "normalized_sha256": f"{index + 1:064x}",
                    "ano_compra": 2040,
                    "sequencial_compra": index + 1,
                    "numero_compra": str(index + 1),
                    "srp": False,
                    "objeto_compra": f"Objeto analytics {index + 1}",
                    "valor_total_estimado": item[4],
                    "valor_total_homologado": item[5],
                    "created_at": now,
                    "updated_at": now,
                }
                for index, item in enumerate(facts)
            ],
        )

    sample = {
        "token": token,
        "run_id": run_id,
        "raw_id": raw_id,
        "cnpjs": (cnpj_a, cnpj_b),
        "organization_a": organizations[cnpj_a],
        "baseline_summary": dict(baseline_summary),
        "unit_codes": tuple(units),
        "modality_ids": tuple(modality_ids),
        "modality_keys": tuple(modalities[value] for value in modality_ids),
        "pncp_keys": tuple(pncp_keys),
        "dates": tuple(dates),
    }
    try:
        yield sample
    finally:
        with engine.begin() as connection:
            connection.execute(
                fact_procurement.delete().where(
                    fact_procurement.c.numero_controle_pncp.in_(sample["pncp_keys"])
                )
            )
            connection.execute(
                dim_unit.delete().where(dim_unit.c.codigo_unidade.in_(sample["unit_codes"]))
            )
            connection.execute(
                dim_organization.delete().where(dim_organization.c.orgao_cnpj.in_(sample["cnpjs"]))
            )
            connection.execute(
                dim_modality.delete().where(
                    dim_modality.c.modalidade_id.in_(sample["modality_ids"])
                )
            )
            connection.execute(dim_date.delete().where(dim_date.c.full_date.in_(sample["dates"])))
            connection.execute(
                raw_api_response.delete().where(raw_api_response.c.id == sample["raw_id"])
            )
            connection.execute(etl_run.delete().where(etl_run.c.id == sample["run_id"]))


@pytest.mark.integration
def test_service_reconciles_kpis_rankings_trends_and_outliers(
    engine: Engine, analytics_sample: dict[str, object]
) -> None:
    """Catch formula drift between summary, rankings, trends, and evidence rows."""
    service = AnalyticsService(engine)
    period = AnalyticsFilters(start_date=date(2040, 1, 1), end_date=date(2040, 6, 30))

    summary = service.summary(period)
    assert summary.procurement_count == 7
    assert summary.estimated_value_count == 4
    assert summary.estimated_total == Decimal("1100.0000")
    assert summary.estimated_average == Decimal("275.0000")
    assert summary.homologated_value_count == 7
    assert summary.homologated_total == Decimal("1150.0000")
    assert summary.homologated_average == Decimal("164.2857142857142857")

    sp = service.summary(
        AnalyticsFilters(start_date=period.start_date, end_date=period.end_date, uf="zz")
    )
    assert sp.procurement_count == 5
    assert sp.estimated_value_count == 2
    assert sp.estimated_total == Decimal("400.0000")
    assert sp.homologated_total == Decimal("130.0000")

    organization_summary = service.summary(
        AnalyticsFilters(
            start_date=period.start_date,
            end_date=period.end_date,
            organization_key=analytics_sample["organization_a"],
        )
    )
    assert organization_summary.procurement_count == 5
    modality_summary = service.summary(
        AnalyticsFilters(
            start_date=period.start_date,
            end_date=period.end_date,
            modality_key=analytics_sample["modality_keys"][0],
        )
    )
    assert modality_summary.procurement_count == 4

    organizations = service.rank(
        RankDimension.ORGANIZATION,
        measure=Measure.HOMOLOGATED,
        filters=period,
        limit=10,
    )
    assert [row.label for row in organizations] == [
        "Órgão Analytics B",
        "Órgão Analytics A",
    ]
    assert [row.key for row in organizations] == list(reversed(analytics_sample["cnpjs"]))
    assert [row.total for row in organizations] == [Decimal("1020.0000"), Decimal("130.0000")]
    assert sum(row.share or Decimal(0) for row in organizations) == Decimal("1")

    states = service.rank(
        RankDimension.STATE,
        measure=Measure.HOMOLOGATED,
        filters=period,
        limit=10,
    )
    assert states[0].key == "UNKNOWN"
    assert states[0].total == Decimal("1000.0000")
    assert next(row.label for row in states if row.key == "ZZ") == "Acre"
    modalities = service.rank(
        RankDimension.MODALITY,
        measure=Measure.HOMOLOGATED,
        filters=period,
        limit=10,
    )
    assert {row.key for row in modalities} == {
        str(value) for value in analytics_sample["modality_ids"]
    }

    trends = service.monthly_trend(period)
    assert [row.month for row in trends] == [
        date(2040, 1, 1),
        date(2040, 2, 1),
        date(2040, 4, 1),
        date(2040, 5, 1),
        date(2040, 6, 1),
    ]
    assert trends[1].homologated_growth_rate == Decimal("1.3333333333333333")
    assert trends[2].homologated_growth_rate is None
    assert trends[4].homologated_growth_rate is None

    distribution = service.distribution(filters=period)
    assert distribution.q1 == Decimal("15.00000")
    assert distribution.q3 == Decimal("45.00000")
    assert distribution.upper_fence == Decimal("90.000000")
    estimated_distribution = service.distribution(Measure.ESTIMATED, period)
    assert estimated_distribution.sample_size == 4
    assert estimated_distribution.maximum == Decimal("500.0000")

    outliers = service.outliers(filters=period)
    assert outliers.distribution == distribution
    assert [(row.numero_controle_pncp, row.value) for row in outliers.outliers] == [
        (analytics_sample["pncp_keys"][4], Decimal("1000.0000"))
    ]

    with engine.connect() as connection:
        global_summary = (
            connection.execute(sa.text("SELECT * FROM gold.analytics_summary")).mappings().one()
        )
        baseline = analytics_sample["baseline_summary"]
        assert global_summary["procurement_count"] - baseline["procurement_count"] == 7
        assert (global_summary["homologated_total"] or 0) - (
            baseline["homologated_total"] or 0
        ) == Decimal("1150.0000")
        organization_view = connection.execute(
            sa.text(
                "SELECT procurement_count, homologated_total "
                "FROM gold.analytics_by_organization WHERE orgao_cnpj = :cnpj"
            ),
            {"cnpj": analytics_sample["cnpjs"][0]},
        ).one()
        assert tuple(organization_view) == (5, Decimal("130.0000"))
        state_view = connection.execute(
            sa.text(
                "SELECT uf_nome, procurement_count, homologated_total "
                "FROM gold.analytics_by_state WHERE uf_sigla = 'ZZ'"
            )
        ).all()
        assert state_view == [("Acre", 5, Decimal("130.0000"))]
        modality_view = connection.execute(
            sa.text(
                "SELECT procurement_count, homologated_total "
                "FROM gold.analytics_by_modality WHERE modalidade_id = :modality"
            ),
            {"modality": analytics_sample["modality_ids"][0]},
        ).one()
        assert tuple(modality_view) == (4, Decimal("90.0000"))
        monthly_view = connection.execute(
            sa.text(
                "SELECT month, homologated_growth_rate FROM gold.analytics_monthly "
                "WHERE month BETWEEN DATE '2040-01-01' AND DATE '2040-06-01' ORDER BY month"
            )
        ).all()
        assert monthly_view[-1] == (date(2040, 6, 1), None)

    with capture_logs() as logs:
        service.summary(period)
        service.rank(RankDimension.STATE, filters=period)
        service.monthly_trend(period)
        service.distribution(filters=period)
        service.outliers(filters=period)
    assert [entry["event"] for entry in logs] == [
        "analytics_summary_completed",
        "analytics_ranking_completed",
        "analytics_monthly_completed",
        "analytics_distribution_completed",
        "analytics_outliers_completed",
    ]
    assert all("filters" in entry for entry in logs)
    assert all("rows" in entry or "sample_size" in entry for entry in logs)

    with engine.begin() as connection:
        connection.execute(
            fact_procurement.update()
            .where(fact_procurement.c.numero_controle_pncp == analytics_sample["pncp_keys"][0])
            .values(valor_total_homologado=Decimal("900.0000"))
        )
    tied = service.rank(
        RankDimension.ORGANIZATION,
        measure=Measure.HOMOLOGATED,
        filters=period,
    )
    assert [row.total for row in tied] == [Decimal("1020.0000"), Decimal("1020.0000")]
    assert [row.key for row in tied] == sorted(analytics_sample["cnpjs"])


@pytest.mark.integration
def test_service_returns_empty_results_for_valid_unmatched_filter(
    engine: Engine, analytics_sample: dict[str, object]
) -> None:
    """Catch fabricated metrics when valid filters match no Gold rows."""
    service = AnalyticsService(engine)
    filters = AnalyticsFilters(start_date=date(2039, 1, 1), end_date=date(2039, 1, 31))

    summary = service.summary(filters)

    assert summary.procurement_count == 0
    assert summary.estimated_total is None
    assert service.rank(RankDimension.STATE, filters=filters) == ()
    assert service.monthly_trend(filters) == ()
    assert service.outliers(Measure.HOMOLOGATED, filters).outliers == ()


@pytest.mark.integration
def test_service_rejects_unbounded_ranking_limit(engine: Engine) -> None:
    """Catch queries that could return an unbounded analytical result set."""
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        AnalyticsService(engine).rank(RankDimension.STATE, limit=101)


@pytest.mark.integration
def test_service_rejects_unsupported_runtime_enums(engine: Engine) -> None:
    """Catch silent fallback to a different financial measure or ranking dimension."""
    service = AnalyticsService(engine)

    with pytest.raises(ValueError):
        service.distribution("invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        service.rank("invalid")  # type: ignore[arg-type]
