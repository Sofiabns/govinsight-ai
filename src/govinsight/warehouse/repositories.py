from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from govinsight.raw.tables import etl_watermark
from govinsight.transform.tables import procurement

from .models import ReconciliationResult, WarehouseStateError, WarehouseWatermarkState
from .tables import dim_date, dim_modality, dim_organization, dim_unit, fact_procurement

DATASET = "procurements"
SILVER_PIPELINE = "silver_procurement"
QUALITY_PIPELINE = "data_quality"
WAREHOUSE_PIPELINE = "gold_procurement"


def _watermark_key(pipeline: str, stage: str) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        etl_watermark.c.pipeline_name == pipeline,
        etl_watermark.c.dataset == DATASET,
        etl_watermark.c.stage == stage,
    )


class WarehouseWatermarkRepository:
    @staticmethod
    def _read(connection: Connection, pipeline: str, stage: str) -> int:
        value = connection.execute(
            sa.select(etl_watermark.c.watermark_value).where(*_watermark_key(pipeline, stage))
        ).scalar_one_or_none()
        if value is None:
            return 0
        raw_id = value.get("last_raw_response_id") if isinstance(value, dict) else None
        if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id < 0:
            raise WarehouseStateError("INVALID_WATERMARK")
        return raw_id

    def read_state(
        self,
        connection: Connection,
        *,
        lock_gold: bool = True,
    ) -> WarehouseWatermarkState:
        if lock_gold:
            connection.execute(
                sa.select(
                    sa.func.pg_advisory_xact_lock(sa.func.hashtext("gold_procurement:procurements"))
                )
            )
        return WarehouseWatermarkState(
            silver=self._read(connection, SILVER_PIPELINE, "silver"),
            quality=self._read(connection, QUALITY_PIPELINE, "quality"),
            gold=self._read(connection, WAREHOUSE_PIPELINE, "gold"),
        )

    def advance(self, connection: Connection, raw_response_id: int) -> None:
        now = datetime.now(UTC)
        statement = postgresql.insert(etl_watermark).values(
            pipeline_name=WAREHOUSE_PIPELINE,
            dataset=DATASET,
            stage="gold",
            watermark_value={"last_raw_response_id": raw_response_id},
            confirmed_at=now,
        )
        stored_id = sa.cast(
            etl_watermark.c.watermark_value["last_raw_response_id"].astext,
            sa.BigInteger(),
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    etl_watermark.c.pipeline_name,
                    etl_watermark.c.dataset,
                    etl_watermark.c.stage,
                ],
                set_={
                    "watermark_value": statement.excluded.watermark_value,
                    "confirmed_at": statement.excluded.confirmed_at,
                },
                where=stored_id < raw_response_id,
            )
        )


def _latest_by(*natural_key: sa.Column) -> sa.Select:
    return (
        sa.select(procurement)
        .distinct(*natural_key)
        .order_by(
            *natural_key,
            procurement.c.data_atualizacao_global.desc(),
            procurement.c.source_raw_response_id.desc(),
        )
    )


def _date_key(value: sa.ColumnElement) -> sa.ColumnElement:
    return (
        sa.cast(sa.extract("year", value), sa.Integer()) * 10000
        + sa.cast(sa.extract("month", value), sa.Integer()) * 100
        + sa.cast(sa.extract("day", value), sa.Integer())
    )


class WarehouseRepository:
    def load_dimensions(self, connection: Connection) -> dict[str, int]:
        now = datetime.now(UTC)
        self._load_dates(connection)
        self._load_organizations(connection, now)
        self._load_units(connection, now)
        self._load_modalities(connection, now)
        return {
            "dates": self._count(connection, dim_date),
            "organizations": self._count(connection, dim_organization),
            "units": self._count(connection, dim_unit),
            "modalities": self._count(connection, dim_modality),
        }

    @staticmethod
    def _count(connection: Connection, table: sa.Table) -> int:
        return connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()

    @staticmethod
    def _load_dates(connection: Connection) -> None:
        date_sources = []
        for column in (
            procurement.c.data_publicacao_pncp,
            procurement.c.data_abertura_proposta,
            procurement.c.data_encerramento_proposta,
        ):
            date_sources.append(
                sa.select(sa.cast(column, sa.Date()).label("full_date")).where(column.is_not(None))
            )
        dates = sa.union(*date_sources).subquery()
        source = sa.select(
            _date_key(dates.c.full_date),
            dates.c.full_date,
            sa.cast(sa.extract("day", dates.c.full_date), sa.SmallInteger()),
            sa.cast(sa.extract("month", dates.c.full_date), sa.SmallInteger()),
            sa.cast(sa.extract("quarter", dates.c.full_date), sa.SmallInteger()),
            sa.cast(sa.extract("year", dates.c.full_date), sa.SmallInteger()),
            sa.cast(sa.extract("isodow", dates.c.full_date), sa.SmallInteger()),
        )
        statement = postgresql.insert(dim_date).from_select(
            ["date_key", "full_date", "day", "month", "quarter", "year", "iso_weekday"],
            source,
        )
        connection.execute(statement.on_conflict_do_nothing(index_elements=[dim_date.c.date_key]))

    @staticmethod
    def _load_organizations(connection: Connection, now: datetime) -> None:
        latest = _latest_by(procurement.c.orgao_cnpj).subquery()
        source = sa.select(
            latest.c.orgao_cnpj,
            latest.c.orgao_razao_social,
            latest.c.poder_id,
            latest.c.esfera_id,
            sa.literal(now),
            sa.literal(now),
        )
        statement = postgresql.insert(dim_organization).from_select(
            [
                "orgao_cnpj",
                "orgao_razao_social",
                "poder_id",
                "esfera_id",
                "created_at",
                "updated_at",
            ],
            source,
        )
        connection.execute(
            statement.on_conflict_do_update(
                constraint="uq_gold_dim_organization_cnpj",
                set_={
                    "orgao_razao_social": statement.excluded.orgao_razao_social,
                    "poder_id": statement.excluded.poder_id,
                    "esfera_id": statement.excluded.esfera_id,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )

    @staticmethod
    def _load_units(connection: Connection, now: datetime) -> None:
        latest = _latest_by(procurement.c.orgao_cnpj, procurement.c.codigo_unidade).subquery()
        source = sa.select(
            latest.c.orgao_cnpj,
            latest.c.codigo_unidade,
            latest.c.nome_unidade,
            latest.c.codigo_ibge,
            latest.c.municipio_nome,
            latest.c.uf_sigla,
            latest.c.uf_nome,
            sa.literal(now),
            sa.literal(now),
        )
        statement = postgresql.insert(dim_unit).from_select(
            [
                "orgao_cnpj",
                "codigo_unidade",
                "nome_unidade",
                "codigo_ibge",
                "municipio_nome",
                "uf_sigla",
                "uf_nome",
                "created_at",
                "updated_at",
            ],
            source,
        )
        connection.execute(
            statement.on_conflict_do_update(
                constraint="uq_gold_dim_unit_natural",
                set_={
                    "nome_unidade": statement.excluded.nome_unidade,
                    "codigo_ibge": statement.excluded.codigo_ibge,
                    "municipio_nome": statement.excluded.municipio_nome,
                    "uf_sigla": statement.excluded.uf_sigla,
                    "uf_nome": statement.excluded.uf_nome,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )

    @staticmethod
    def _load_modalities(connection: Connection, now: datetime) -> None:
        latest = _latest_by(procurement.c.modalidade_id).subquery()
        source = sa.select(
            latest.c.modalidade_id,
            latest.c.modalidade_nome,
            sa.literal(now),
            sa.literal(now),
        )
        statement = postgresql.insert(dim_modality).from_select(
            ["modalidade_id", "modalidade_nome", "created_at", "updated_at"], source
        )
        connection.execute(
            statement.on_conflict_do_update(
                constraint="uq_gold_dim_modality_id",
                set_={
                    "modalidade_nome": statement.excluded.modalidade_nome,
                    "updated_at": statement.excluded.updated_at,
                },
            )
        )

    def load_facts(self, connection: Connection) -> int:
        now = datetime.now(UTC)
        publication = dim_date.alias("publication")
        opening = dim_date.alias("opening")
        closing = dim_date.alias("closing")
        source = (
            sa.select(
                procurement.c.numero_controle_pncp,
                dim_organization.c.organization_key,
                dim_unit.c.unit_key,
                dim_modality.c.modality_key,
                publication.c.date_key,
                opening.c.date_key,
                closing.c.date_key,
                procurement.c.source_raw_response_id,
                procurement.c.normalized_sha256,
                procurement.c.ano_compra,
                procurement.c.sequencial_compra,
                procurement.c.numero_compra,
                procurement.c.srp,
                procurement.c.objeto_compra,
                procurement.c.situacao_compra_id,
                procurement.c.situacao_compra_nome,
                procurement.c.tipo_instrumento_codigo,
                procurement.c.tipo_instrumento_nome,
                procurement.c.valor_total_estimado,
                procurement.c.valor_total_homologado,
                sa.literal(now),
                sa.literal(now),
            )
            .join(
                dim_organization,
                procurement.c.orgao_cnpj == dim_organization.c.orgao_cnpj,
            )
            .join(
                dim_unit,
                sa.and_(
                    procurement.c.orgao_cnpj == dim_unit.c.orgao_cnpj,
                    procurement.c.codigo_unidade == dim_unit.c.codigo_unidade,
                ),
            )
            .join(dim_modality, procurement.c.modalidade_id == dim_modality.c.modalidade_id)
            .join(
                publication,
                sa.cast(procurement.c.data_publicacao_pncp, sa.Date()) == publication.c.full_date,
            )
            .outerjoin(
                opening,
                sa.cast(procurement.c.data_abertura_proposta, sa.Date()) == opening.c.full_date,
            )
            .outerjoin(
                closing,
                sa.cast(procurement.c.data_encerramento_proposta, sa.Date()) == closing.c.full_date,
            )
        )
        columns = [
            "numero_controle_pncp",
            "organization_key",
            "unit_key",
            "modality_key",
            "publication_date_key",
            "opening_date_key",
            "closing_date_key",
            "source_raw_response_id",
            "normalized_sha256",
            "ano_compra",
            "sequencial_compra",
            "numero_compra",
            "srp",
            "objeto_compra",
            "situacao_compra_id",
            "situacao_compra_nome",
            "tipo_instrumento_codigo",
            "tipo_instrumento_nome",
            "valor_total_estimado",
            "valor_total_homologado",
            "created_at",
            "updated_at",
        ]
        statement = postgresql.insert(fact_procurement).from_select(columns, source)
        mutable = [
            name
            for name in columns
            if name not in {"numero_controle_pncp", "created_at", "updated_at"}
        ]
        update_values = {name: getattr(statement.excluded, name) for name in mutable}
        update_values["updated_at"] = statement.excluded.updated_at
        connection.execute(
            statement.on_conflict_do_update(
                constraint="uq_gold_fact_procurement_pncp",
                set_=update_values,
            )
        )
        return self._count(connection, fact_procurement)

    def reconcile(self, connection: Connection) -> ReconciliationResult:
        silver_totals = connection.execute(
            sa.select(
                sa.func.count().label("rows"),
                sa.func.coalesce(sa.func.sum(procurement.c.valor_total_estimado), 0).label(
                    "estimated"
                ),
                sa.func.count()
                .filter(procurement.c.valor_total_estimado.is_(None))
                .label("estimated_nulls"),
                sa.func.coalesce(sa.func.sum(procurement.c.valor_total_homologado), 0).label(
                    "homologated"
                ),
                sa.func.count()
                .filter(procurement.c.valor_total_homologado.is_(None))
                .label("homologated_nulls"),
            )
        ).one()
        fact_totals = connection.execute(
            sa.select(
                sa.func.count().label("rows"),
                sa.func.coalesce(sa.func.sum(fact_procurement.c.valor_total_estimado), 0).label(
                    "estimated"
                ),
                sa.func.count()
                .filter(fact_procurement.c.valor_total_estimado.is_(None))
                .label("estimated_nulls"),
                sa.func.coalesce(sa.func.sum(fact_procurement.c.valor_total_homologado), 0).label(
                    "homologated"
                ),
                sa.func.count()
                .filter(fact_procurement.c.valor_total_homologado.is_(None))
                .label("homologated_nulls"),
            )
        ).one()
        missing_in_fact = connection.execute(
            sa.select(sa.func.count())
            .select_from(
                procurement.outerjoin(
                    fact_procurement,
                    procurement.c.numero_controle_pncp == fact_procurement.c.numero_controle_pncp,
                )
            )
            .where(fact_procurement.c.procurement_key.is_(None))
        ).scalar_one()
        missing_in_silver = connection.execute(
            sa.select(sa.func.count())
            .select_from(
                fact_procurement.outerjoin(
                    procurement,
                    fact_procurement.c.numero_controle_pncp == procurement.c.numero_controle_pncp,
                )
            )
            .where(procurement.c.numero_controle_pncp.is_(None))
        ).scalar_one()
        orphan_foreign_keys = self._orphan_count(connection)
        lineage_mismatches = connection.execute(
            sa.select(sa.func.count())
            .select_from(
                fact_procurement.join(
                    procurement,
                    fact_procurement.c.numero_controle_pncp == procurement.c.numero_controle_pncp,
                )
            )
            .where(
                sa.or_(
                    fact_procurement.c.source_raw_response_id
                    != procurement.c.source_raw_response_id,
                    fact_procurement.c.normalized_sha256 != procurement.c.normalized_sha256,
                )
            )
        ).scalar_one()
        return ReconciliationResult(
            silver_rows=silver_totals.rows,
            fact_rows=fact_totals.rows,
            missing_in_fact=missing_in_fact,
            missing_in_silver=missing_in_silver,
            orphan_foreign_keys=orphan_foreign_keys,
            lineage_mismatches=lineage_mismatches,
            estimated_silver=Decimal(silver_totals.estimated),
            estimated_fact=Decimal(fact_totals.estimated),
            estimated_nulls_silver=silver_totals.estimated_nulls,
            estimated_nulls_fact=fact_totals.estimated_nulls,
            homologated_silver=Decimal(silver_totals.homologated),
            homologated_fact=Decimal(fact_totals.homologated),
            homologated_nulls_silver=silver_totals.homologated_nulls,
            homologated_nulls_fact=fact_totals.homologated_nulls,
        )

    @staticmethod
    def _orphan_count(connection: Connection) -> int:
        organization = dim_organization.alias("organization_check")
        unit = dim_unit.alias("unit_check")
        modality = dim_modality.alias("modality_check")
        publication = dim_date.alias("publication_check")
        opening = dim_date.alias("opening_check")
        closing = dim_date.alias("closing_check")
        joined = (
            fact_procurement.outerjoin(
                organization,
                fact_procurement.c.organization_key == organization.c.organization_key,
            )
            .outerjoin(unit, fact_procurement.c.unit_key == unit.c.unit_key)
            .outerjoin(modality, fact_procurement.c.modality_key == modality.c.modality_key)
            .outerjoin(
                publication,
                fact_procurement.c.publication_date_key == publication.c.date_key,
            )
            .outerjoin(opening, fact_procurement.c.opening_date_key == opening.c.date_key)
            .outerjoin(closing, fact_procurement.c.closing_date_key == closing.c.date_key)
        )
        return connection.execute(
            sa.select(sa.func.count())
            .select_from(joined)
            .where(
                sa.or_(
                    organization.c.organization_key.is_(None),
                    unit.c.unit_key.is_(None),
                    modality.c.modality_key.is_(None),
                    publication.c.date_key.is_(None),
                    sa.and_(
                        fact_procurement.c.opening_date_key.is_not(None),
                        opening.c.date_key.is_(None),
                    ),
                    sa.and_(
                        fact_procurement.c.closing_date_key.is_not(None),
                        closing.c.date_key.is_(None),
                    ),
                )
            )
        ).scalar_one()


__all__ = ["WarehouseRepository", "WarehouseWatermarkRepository"]
