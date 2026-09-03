"""Create canonical procurement analytics views.

Revision ID: 20260830_0006
Revises: 20260826_0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260830_0006"
down_revision: str | None = "20260826_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW gold.analytics_procurement_base AS
        SELECT
            f.procurement_key,
            f.numero_controle_pncp,
            d.full_date AS publication_date,
            o.organization_key,
            o.orgao_cnpj,
            o.orgao_razao_social,
            u.unit_key,
            u.uf_sigla,
            u.uf_nome,
            m.modality_key,
            m.modalidade_id,
            m.modalidade_nome,
            f.valor_total_estimado,
            f.valor_total_homologado
        FROM gold.fact_procurement AS f
        JOIN gold.dim_date AS d
          ON d.date_key = f.publication_date_key
        JOIN gold.dim_organization AS o
          ON o.organization_key = f.organization_key
        JOIN gold.dim_unit AS u
          ON u.unit_key = f.unit_key
        JOIN gold.dim_modality AS m
          ON m.modality_key = f.modality_key
        """
    )
    op.execute(
        """
        CREATE VIEW gold.analytics_summary AS
        SELECT
            COUNT(*)::bigint AS procurement_count,
            COUNT(valor_total_estimado)::bigint AS estimated_value_count,
            SUM(valor_total_estimado) AS estimated_total,
            AVG(valor_total_estimado) AS estimated_average,
            COUNT(valor_total_homologado)::bigint AS homologated_value_count,
            SUM(valor_total_homologado) AS homologated_total,
            AVG(valor_total_homologado) AS homologated_average
        FROM gold.analytics_procurement_base
        """
    )
    op.execute(
        """
        CREATE VIEW gold.analytics_by_organization AS
        SELECT
            organization_key,
            orgao_cnpj,
            orgao_razao_social,
            COUNT(*)::bigint AS procurement_count,
            SUM(valor_total_estimado) AS estimated_total,
            AVG(valor_total_estimado) AS estimated_average,
            SUM(valor_total_homologado) AS homologated_total,
            AVG(valor_total_homologado) AS homologated_average,
            SUM(valor_total_estimado)
                / NULLIF(SUM(SUM(valor_total_estimado)) OVER (), 0) AS estimated_share,
            SUM(valor_total_homologado)
                / NULLIF(SUM(SUM(valor_total_homologado)) OVER (), 0) AS homologated_share
        FROM gold.analytics_procurement_base
        GROUP BY organization_key, orgao_cnpj, orgao_razao_social
        """
    )
    op.execute(
        """
        CREATE VIEW gold.analytics_by_state AS
        SELECT
            COALESCE(uf_sigla, 'UNKNOWN') AS uf_sigla,
            MAX(COALESCE(uf_nome, 'Localidade não informada')) AS uf_nome,
            COUNT(*)::bigint AS procurement_count,
            SUM(valor_total_estimado) AS estimated_total,
            AVG(valor_total_estimado) AS estimated_average,
            SUM(valor_total_homologado) AS homologated_total,
            AVG(valor_total_homologado) AS homologated_average,
            SUM(valor_total_estimado)
                / NULLIF(SUM(SUM(valor_total_estimado)) OVER (), 0) AS estimated_share,
            SUM(valor_total_homologado)
                / NULLIF(SUM(SUM(valor_total_homologado)) OVER (), 0) AS homologated_share
        FROM gold.analytics_procurement_base
        GROUP BY COALESCE(uf_sigla, 'UNKNOWN')
        """
    )
    op.execute(
        """
        CREATE VIEW gold.analytics_by_modality AS
        SELECT
            modality_key,
            modalidade_id,
            modalidade_nome,
            COUNT(*)::bigint AS procurement_count,
            SUM(valor_total_estimado) AS estimated_total,
            AVG(valor_total_estimado) AS estimated_average,
            SUM(valor_total_homologado) AS homologated_total,
            AVG(valor_total_homologado) AS homologated_average,
            SUM(valor_total_estimado)
                / NULLIF(SUM(SUM(valor_total_estimado)) OVER (), 0) AS estimated_share,
            SUM(valor_total_homologado)
                / NULLIF(SUM(SUM(valor_total_homologado)) OVER (), 0) AS homologated_share
        FROM gold.analytics_procurement_base
        GROUP BY modality_key, modalidade_id, modalidade_nome
        """
    )
    op.execute(
        """
        CREATE VIEW gold.analytics_monthly AS
        WITH monthly AS (
            SELECT
                date_trunc('month', publication_date)::date AS month,
                COUNT(*)::bigint AS procurement_count,
                SUM(valor_total_estimado) AS estimated_total,
                AVG(valor_total_estimado) AS estimated_average,
                SUM(valor_total_homologado) AS homologated_total,
                AVG(valor_total_homologado) AS homologated_average
            FROM gold.analytics_procurement_base
            GROUP BY date_trunc('month', publication_date)::date
        ), lagged AS (
            SELECT
                monthly.*,
                LAG(month) OVER (ORDER BY month) AS previous_month,
                LAG(estimated_total) OVER (ORDER BY month) AS previous_estimated_total,
                LAG(homologated_total) OVER (ORDER BY month) AS previous_homologated_total
            FROM monthly
        )
        SELECT
            month,
            procurement_count,
            estimated_total,
            estimated_average,
            homologated_total,
            homologated_average,
            CASE
                WHEN previous_month = (month - INTERVAL '1 month')::date
                THEN (estimated_total - previous_estimated_total)
                    / NULLIF(previous_estimated_total, 0)
            END AS estimated_growth_rate,
            CASE
                WHEN previous_month = (month - INTERVAL '1 month')::date
                THEN (homologated_total - previous_homologated_total)
                    / NULLIF(previous_homologated_total, 0)
            END AS homologated_growth_rate
        FROM lagged
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS gold.analytics_monthly")
    op.execute("DROP VIEW IF EXISTS gold.analytics_by_modality")
    op.execute("DROP VIEW IF EXISTS gold.analytics_by_state")
    op.execute("DROP VIEW IF EXISTS gold.analytics_by_organization")
    op.execute("DROP VIEW IF EXISTS gold.analytics_summary")
    op.execute("DROP VIEW IF EXISTS gold.analytics_procurement_base")
