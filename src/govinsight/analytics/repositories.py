from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Connection

from govinsight.analytics.models import AnalyticsFilters, Measure, RankDimension

analytics_base = sa.table(
    "analytics_procurement_base",
    sa.column("numero_controle_pncp", sa.Text()),
    sa.column("publication_date", sa.Date()),
    sa.column("organization_key", sa.BigInteger()),
    sa.column("orgao_cnpj", sa.Text()),
    sa.column("orgao_razao_social", sa.Text()),
    sa.column("uf_sigla", sa.Text()),
    sa.column("uf_nome", sa.Text()),
    sa.column("modality_key", sa.BigInteger()),
    sa.column("modalidade_id", sa.Integer()),
    sa.column("modalidade_nome", sa.Text()),
    sa.column("valor_total_estimado", sa.Numeric()),
    sa.column("valor_total_homologado", sa.Numeric()),
    schema="gold",
)


@dataclass(frozen=True)
class ValueRow:
    numero_controle_pncp: str
    value: Decimal


def _measure_column(measure: Measure) -> sa.ColumnClause:
    if measure is Measure.ESTIMATED:
        return analytics_base.c.valor_total_estimado
    return analytics_base.c.valor_total_homologado


def _apply_filters(statement: sa.Select, filters: AnalyticsFilters) -> sa.Select:
    if filters.start_date is not None:
        statement = statement.where(analytics_base.c.publication_date >= filters.start_date)
    if filters.end_date is not None:
        statement = statement.where(analytics_base.c.publication_date <= filters.end_date)
    if filters.organization_key is not None:
        statement = statement.where(analytics_base.c.organization_key == filters.organization_key)
    if filters.uf is not None:
        statement = statement.where(
            sa.func.coalesce(analytics_base.c.uf_sigla, "UNKNOWN") == filters.uf
        )
    if filters.modality_key is not None:
        statement = statement.where(analytics_base.c.modality_key == filters.modality_key)
    return statement


class AnalyticsRepository:
    def summary(self, connection: Connection, filters: AnalyticsFilters) -> sa.Row:
        statement = sa.select(
            sa.func.count().label("procurement_count"),
            sa.func.count(analytics_base.c.valor_total_estimado).label("estimated_value_count"),
            sa.func.sum(analytics_base.c.valor_total_estimado).label("estimated_total"),
            sa.func.avg(analytics_base.c.valor_total_estimado).label("estimated_average"),
            sa.func.count(analytics_base.c.valor_total_homologado).label("homologated_value_count"),
            sa.func.sum(analytics_base.c.valor_total_homologado).label("homologated_total"),
            sa.func.avg(analytics_base.c.valor_total_homologado).label("homologated_average"),
        ).select_from(analytics_base)
        return connection.execute(_apply_filters(statement, filters)).one()

    def rank(
        self,
        connection: Connection,
        dimension: RankDimension,
        measure: Measure,
        filters: AnalyticsFilters,
        limit: int,
    ) -> list[sa.Row]:
        if dimension is RankDimension.ORGANIZATION:
            key = sa.cast(analytics_base.c.organization_key, sa.Text()).label("key")
            label = analytics_base.c.orgao_razao_social.label("label")
            group_columns = [analytics_base.c.organization_key, analytics_base.c.orgao_razao_social]
        elif dimension is RankDimension.STATE:
            key = sa.func.coalesce(analytics_base.c.uf_sigla, "UNKNOWN").label("key")
            label = sa.func.coalesce(analytics_base.c.uf_nome, "Localidade não informada").label(
                "label"
            )
            group_columns = [key, label]
        else:
            key = sa.cast(analytics_base.c.modality_key, sa.Text()).label("key")
            label = analytics_base.c.modalidade_nome.label("label")
            group_columns = [analytics_base.c.modality_key, analytics_base.c.modalidade_nome]

        value = _measure_column(measure)
        grouped = _apply_filters(
            sa.select(
                key,
                label,
                sa.func.count().label("procurement_count"),
                sa.func.sum(value).label("total"),
                sa.func.avg(value).label("average"),
            ).select_from(analytics_base),
            filters,
        ).group_by(*group_columns)
        result = grouped.subquery()
        statement = (
            sa.select(
                result,
                (result.c.total / sa.func.nullif(sa.func.sum(result.c.total).over(), 0)).label(
                    "share"
                ),
            )
            .order_by(result.c.total.desc().nulls_last(), result.c.key.asc())
            .limit(limit)
        )
        return list(connection.execute(statement).all())

    def monthly(self, connection: Connection, filters: AnalyticsFilters) -> list[sa.Row]:
        month = sa.cast(
            sa.func.date_trunc("month", analytics_base.c.publication_date), sa.Date()
        ).label("month")
        grouped = _apply_filters(
            sa.select(
                month,
                sa.func.count().label("procurement_count"),
                sa.func.sum(analytics_base.c.valor_total_estimado).label("estimated_total"),
                sa.func.avg(analytics_base.c.valor_total_estimado).label("estimated_average"),
                sa.func.sum(analytics_base.c.valor_total_homologado).label("homologated_total"),
                sa.func.avg(analytics_base.c.valor_total_homologado).label("homologated_average"),
            ).select_from(analytics_base),
            filters,
        ).group_by(month)
        monthly = grouped.subquery()
        lagged = sa.select(
            monthly,
            sa.func.lag(monthly.c.month).over(order_by=monthly.c.month).label("previous_month"),
            sa.func.lag(monthly.c.estimated_total)
            .over(order_by=monthly.c.month)
            .label("previous_estimated_total"),
            sa.func.lag(monthly.c.homologated_total)
            .over(order_by=monthly.c.month)
            .label("previous_homologated_total"),
        ).subquery()
        prior_calendar_month = sa.cast(lagged.c.month - sa.text("INTERVAL '1 month'"), sa.Date())
        statement = sa.select(
            lagged.c.month,
            lagged.c.procurement_count,
            lagged.c.estimated_total,
            lagged.c.estimated_average,
            lagged.c.homologated_total,
            lagged.c.homologated_average,
            sa.case(
                (
                    lagged.c.previous_month == prior_calendar_month,
                    (lagged.c.estimated_total - lagged.c.previous_estimated_total)
                    / sa.func.nullif(lagged.c.previous_estimated_total, 0),
                )
            ).label("estimated_growth_rate"),
            sa.case(
                (
                    lagged.c.previous_month == prior_calendar_month,
                    (lagged.c.homologated_total - lagged.c.previous_homologated_total)
                    / sa.func.nullif(lagged.c.previous_homologated_total, 0),
                )
            ).label("homologated_growth_rate"),
        ).order_by(lagged.c.month)
        return list(connection.execute(statement).all())

    def values(
        self, connection: Connection, measure: Measure, filters: AnalyticsFilters
    ) -> list[ValueRow]:
        value = _measure_column(measure)
        statement = _apply_filters(
            sa.select(
                analytics_base.c.numero_controle_pncp,
                value.label("value"),
            )
            .select_from(analytics_base)
            .where(value.is_not(None)),
            filters,
        ).order_by(analytics_base.c.numero_controle_pncp)
        return [
            ValueRow(row.numero_controle_pncp, row.value) for row in connection.execute(statement)
        ]


__all__ = ["AnalyticsRepository", "ValueRow"]
