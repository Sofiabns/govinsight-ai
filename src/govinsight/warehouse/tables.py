import sqlalchemy as sa

from govinsight.raw.tables import metadata

dim_date = sa.Table(
    "dim_date",
    metadata,
    sa.Column("date_key", sa.Integer(), primary_key=True),
    sa.Column("full_date", sa.Date(), nullable=False),
    sa.Column("day", sa.SmallInteger(), nullable=False),
    sa.Column("month", sa.SmallInteger(), nullable=False),
    sa.Column("quarter", sa.SmallInteger(), nullable=False),
    sa.Column("year", sa.SmallInteger(), nullable=False),
    sa.Column("iso_weekday", sa.SmallInteger(), nullable=False),
    sa.CheckConstraint("day BETWEEN 1 AND 31", name="ck_gold_dim_date_day"),
    sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_gold_dim_date_month"),
    sa.CheckConstraint("quarter BETWEEN 1 AND 4", name="ck_gold_dim_date_quarter"),
    sa.CheckConstraint("iso_weekday BETWEEN 1 AND 7", name="ck_gold_dim_date_weekday"),
    sa.UniqueConstraint("full_date", name="uq_gold_dim_date_full_date"),
    schema="gold",
)

dim_organization = sa.Table(
    "dim_organization",
    metadata,
    sa.Column("organization_key", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("orgao_cnpj", sa.CHAR(14), nullable=False),
    sa.Column("orgao_razao_social", sa.Text(), nullable=False),
    sa.Column("poder_id", sa.Text()),
    sa.Column("esfera_id", sa.Text()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("orgao_cnpj ~ '^[0-9]{14}$'", name="ck_gold_dim_organization_cnpj"),
    sa.UniqueConstraint("orgao_cnpj", name="uq_gold_dim_organization_cnpj"),
    schema="gold",
)

dim_unit = sa.Table(
    "dim_unit",
    metadata,
    sa.Column("unit_key", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("orgao_cnpj", sa.CHAR(14), nullable=False),
    sa.Column("codigo_unidade", sa.Text(), nullable=False),
    sa.Column("nome_unidade", sa.Text(), nullable=False),
    sa.Column("codigo_ibge", sa.CHAR(7)),
    sa.Column("municipio_nome", sa.Text()),
    sa.Column("uf_sigla", sa.CHAR(2)),
    sa.Column("uf_nome", sa.Text()),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("orgao_cnpj ~ '^[0-9]{14}$'", name="ck_gold_dim_unit_cnpj"),
    sa.CheckConstraint(
        "codigo_ibge IS NULL OR codigo_ibge ~ '^[0-9]{7}$'",
        name="ck_gold_dim_unit_ibge",
    ),
    sa.CheckConstraint(
        "uf_sigla IS NULL OR uf_sigla ~ '^[A-Z]{2}$'",
        name="ck_gold_dim_unit_uf",
    ),
    sa.UniqueConstraint("orgao_cnpj", "codigo_unidade", name="uq_gold_dim_unit_natural"),
    schema="gold",
)

dim_modality = sa.Table(
    "dim_modality",
    metadata,
    sa.Column("modality_key", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("modalidade_id", sa.Integer(), nullable=False),
    sa.Column("modalidade_nome", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("modalidade_id", name="uq_gold_dim_modality_id"),
    schema="gold",
)

fact_procurement = sa.Table(
    "fact_procurement",
    metadata,
    sa.Column("procurement_key", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("numero_controle_pncp", sa.Text(), nullable=False),
    sa.Column(
        "organization_key",
        sa.BigInteger(),
        sa.ForeignKey(
            "gold.dim_organization.organization_key",
            name="fk_gold_fact_organization",
        ),
        nullable=False,
    ),
    sa.Column(
        "unit_key",
        sa.BigInteger(),
        sa.ForeignKey("gold.dim_unit.unit_key", name="fk_gold_fact_unit"),
        nullable=False,
    ),
    sa.Column(
        "modality_key",
        sa.BigInteger(),
        sa.ForeignKey("gold.dim_modality.modality_key", name="fk_gold_fact_modality"),
        nullable=False,
    ),
    sa.Column(
        "publication_date_key",
        sa.Integer(),
        sa.ForeignKey("gold.dim_date.date_key", name="fk_gold_fact_publication_date"),
        nullable=False,
    ),
    sa.Column(
        "opening_date_key",
        sa.Integer(),
        sa.ForeignKey("gold.dim_date.date_key", name="fk_gold_fact_opening_date"),
    ),
    sa.Column(
        "closing_date_key",
        sa.Integer(),
        sa.ForeignKey("gold.dim_date.date_key", name="fk_gold_fact_closing_date"),
    ),
    sa.Column(
        "source_raw_response_id",
        sa.BigInteger(),
        sa.ForeignKey("bronze.raw_api_response.id", name="fk_gold_fact_raw"),
        nullable=False,
    ),
    sa.Column("normalized_sha256", sa.CHAR(64), nullable=False),
    sa.Column("ano_compra", sa.Integer(), nullable=False),
    sa.Column("sequencial_compra", sa.Integer(), nullable=False),
    sa.Column("numero_compra", sa.Text()),
    sa.Column("srp", sa.Boolean(), nullable=False),
    sa.Column("objeto_compra", sa.Text(), nullable=False),
    sa.Column("situacao_compra_id", sa.Integer()),
    sa.Column("situacao_compra_nome", sa.Text()),
    sa.Column("tipo_instrumento_codigo", sa.Integer()),
    sa.Column("tipo_instrumento_nome", sa.Text()),
    sa.Column("valor_total_estimado", sa.Numeric(19, 4)),
    sa.Column("valor_total_homologado", sa.Numeric(19, 4)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "normalized_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_gold_fact_procurement_hash",
    ),
    sa.CheckConstraint(
        "(valor_total_estimado IS NULL OR valor_total_estimado >= 0) AND "
        "(valor_total_homologado IS NULL OR valor_total_homologado >= 0)",
        name="ck_gold_fact_procurement_values",
    ),
    sa.UniqueConstraint("numero_controle_pncp", name="uq_gold_fact_procurement_pncp"),
    sa.Index("ix_gold_fact_organization", "organization_key"),
    sa.Index("ix_gold_fact_unit", "unit_key"),
    sa.Index("ix_gold_fact_modality", "modality_key"),
    sa.Index("ix_gold_fact_publication_date", "publication_date_key"),
    sa.Index("ix_gold_fact_year", "ano_compra"),
    schema="gold",
)

__all__ = [
    "dim_date",
    "dim_modality",
    "dim_organization",
    "dim_unit",
    "fact_procurement",
]
