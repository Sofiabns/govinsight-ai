"""Create the Gold procurement star schema.

Revision ID: 20260826_0005
Revises: 20260826_0004
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_0005"
down_revision: str | Sequence[str] | None = "20260826_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dim_date",
        sa.Column("date_key", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("date_key", name="pk_gold_dim_date"),
        sa.UniqueConstraint("full_date", name="uq_gold_dim_date_full_date"),
        schema="gold",
    )
    op.create_table(
        "dim_organization",
        sa.Column("organization_key", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("orgao_cnpj", sa.CHAR(14), nullable=False),
        sa.Column("orgao_razao_social", sa.Text(), nullable=False),
        sa.Column("poder_id", sa.Text()),
        sa.Column("esfera_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("orgao_cnpj ~ '^[0-9]{14}$'", name="ck_gold_dim_organization_cnpj"),
        sa.PrimaryKeyConstraint("organization_key", name="pk_gold_dim_organization"),
        sa.UniqueConstraint("orgao_cnpj", name="uq_gold_dim_organization_cnpj"),
        schema="gold",
    )
    op.create_table(
        "dim_unit",
        sa.Column("unit_key", sa.BigInteger(), sa.Identity(), nullable=False),
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
        sa.PrimaryKeyConstraint("unit_key", name="pk_gold_dim_unit"),
        sa.UniqueConstraint("orgao_cnpj", "codigo_unidade", name="uq_gold_dim_unit_natural"),
        schema="gold",
    )
    op.create_table(
        "dim_modality",
        sa.Column("modality_key", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("modalidade_id", sa.Integer(), nullable=False),
        sa.Column("modalidade_nome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("modality_key", name="pk_gold_dim_modality"),
        sa.UniqueConstraint("modalidade_id", name="uq_gold_dim_modality_id"),
        schema="gold",
    )
    op.create_table(
        "fact_procurement",
        sa.Column("procurement_key", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("numero_controle_pncp", sa.Text(), nullable=False),
        sa.Column("organization_key", sa.BigInteger(), nullable=False),
        sa.Column("unit_key", sa.BigInteger(), nullable=False),
        sa.Column("modality_key", sa.BigInteger(), nullable=False),
        sa.Column("publication_date_key", sa.Integer(), nullable=False),
        sa.Column("opening_date_key", sa.Integer()),
        sa.Column("closing_date_key", sa.Integer()),
        sa.Column("source_raw_response_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_key"],
            ["gold.dim_organization.organization_key"],
            name="fk_gold_fact_organization",
        ),
        sa.ForeignKeyConstraint(["unit_key"], ["gold.dim_unit.unit_key"], name="fk_gold_fact_unit"),
        sa.ForeignKeyConstraint(
            ["modality_key"],
            ["gold.dim_modality.modality_key"],
            name="fk_gold_fact_modality",
        ),
        sa.ForeignKeyConstraint(
            ["publication_date_key"],
            ["gold.dim_date.date_key"],
            name="fk_gold_fact_publication_date",
        ),
        sa.ForeignKeyConstraint(
            ["opening_date_key"],
            ["gold.dim_date.date_key"],
            name="fk_gold_fact_opening_date",
        ),
        sa.ForeignKeyConstraint(
            ["closing_date_key"],
            ["gold.dim_date.date_key"],
            name="fk_gold_fact_closing_date",
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_response_id"],
            ["bronze.raw_api_response.id"],
            name="fk_gold_fact_raw",
        ),
        sa.PrimaryKeyConstraint("procurement_key", name="pk_gold_fact_procurement"),
        sa.UniqueConstraint("numero_controle_pncp", name="uq_gold_fact_procurement_pncp"),
        schema="gold",
    )
    op.create_index(
        "ix_gold_fact_organization",
        "fact_procurement",
        ["organization_key"],
        schema="gold",
    )
    op.create_index("ix_gold_fact_unit", "fact_procurement", ["unit_key"], schema="gold")
    op.create_index(
        "ix_gold_fact_modality",
        "fact_procurement",
        ["modality_key"],
        schema="gold",
    )
    op.create_index(
        "ix_gold_fact_publication_date",
        "fact_procurement",
        ["publication_date_key"],
        schema="gold",
    )
    op.create_index("ix_gold_fact_year", "fact_procurement", ["ano_compra"], schema="gold")


def downgrade() -> None:
    op.drop_index("ix_gold_fact_year", table_name="fact_procurement", schema="gold")
    op.drop_index("ix_gold_fact_publication_date", table_name="fact_procurement", schema="gold")
    op.drop_index("ix_gold_fact_modality", table_name="fact_procurement", schema="gold")
    op.drop_index("ix_gold_fact_unit", table_name="fact_procurement", schema="gold")
    op.drop_index("ix_gold_fact_organization", table_name="fact_procurement", schema="gold")
    op.drop_table("fact_procurement", schema="gold")
    op.drop_table("dim_modality", schema="gold")
    op.drop_table("dim_unit", schema="gold")
    op.drop_table("dim_organization", schema="gold")
    op.drop_table("dim_date", schema="gold")
