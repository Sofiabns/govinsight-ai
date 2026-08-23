"""Create Silver procurement and quarantine tables.

Revision ID: 20260823_0003
Revises: 20260817_0002
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260823_0003"
down_revision: str | Sequence[str] | None = "20260817_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "procurement",
        sa.Column("numero_controle_pncp", sa.Text(), nullable=False),
        sa.Column("source_raw_response_id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_index", sa.Integer(), nullable=False),
        sa.Column("normalized_sha256", sa.CHAR(64), nullable=False),
        sa.Column("srp", sa.Boolean(), nullable=False),
        sa.Column("orgao_cnpj", sa.CHAR(14), nullable=False),
        sa.Column("orgao_razao_social", sa.Text(), nullable=False),
        sa.Column("poder_id", sa.Text()),
        sa.Column("esfera_id", sa.Text()),
        sa.Column("ano_compra", sa.Integer(), nullable=False),
        sa.Column("sequencial_compra", sa.Integer(), nullable=False),
        sa.Column("numero_compra", sa.Text()),
        sa.Column("codigo_unidade", sa.Text(), nullable=False),
        sa.Column("nome_unidade", sa.Text(), nullable=False),
        sa.Column("codigo_ibge", sa.CHAR(7)),
        sa.Column("municipio_nome", sa.Text()),
        sa.Column("uf_sigla", sa.CHAR(2)),
        sa.Column("uf_nome", sa.Text()),
        sa.Column("amparo_legal_codigo", sa.Integer()),
        sa.Column("amparo_legal_nome", sa.Text()),
        sa.Column("amparo_legal_descricao", sa.Text()),
        sa.Column("modalidade_id", sa.Integer(), nullable=False),
        sa.Column("modalidade_nome", sa.Text(), nullable=False),
        sa.Column("modo_disputa_id", sa.Integer()),
        sa.Column("modo_disputa_nome", sa.Text()),
        sa.Column("situacao_compra_id", sa.Integer()),
        sa.Column("situacao_compra_nome", sa.Text()),
        sa.Column("tipo_instrumento_codigo", sa.Integer()),
        sa.Column("tipo_instrumento_nome", sa.Text()),
        sa.Column("data_inclusao", sa.DateTime()),
        sa.Column("data_publicacao_pncp", sa.DateTime(), nullable=False),
        sa.Column("data_atualizacao", sa.DateTime()),
        sa.Column("data_atualizacao_global", sa.DateTime(), nullable=False),
        sa.Column("data_abertura_proposta", sa.DateTime()),
        sa.Column("data_encerramento_proposta", sa.DateTime()),
        sa.Column("processo", sa.Text()),
        sa.Column("objeto_compra", sa.Text(), nullable=False),
        sa.Column("informacao_complementar", sa.Text()),
        sa.Column("link_sistema_origem", sa.Text()),
        sa.Column("link_processo_eletronico", sa.Text()),
        sa.Column("justificativa_presencial", sa.Text()),
        sa.Column("usuario_nome", sa.Text()),
        sa.Column("valor_total_estimado", sa.Numeric(19, 4)),
        sa.Column("valor_total_homologado", sa.Numeric(19, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_record_index >= 0", name="ck_silver_procurement_record_index"
        ),
        sa.CheckConstraint(
            "orgao_cnpj ~ '^[0-9]{14}$'", name="ck_silver_procurement_cnpj"
        ),
        sa.CheckConstraint(
            "normalized_sha256 ~ '^[0-9a-f]{64}$'", name="ck_silver_procurement_hash"
        ),
        sa.CheckConstraint(
            "uf_sigla IS NULL OR uf_sigla ~ '^[A-Z]{2}$'",
            name="ck_silver_procurement_uf",
        ),
        sa.CheckConstraint(
            "codigo_ibge IS NULL OR codigo_ibge ~ '^[0-9]{7}$'",
            name="ck_silver_procurement_ibge",
        ),
        sa.CheckConstraint(
            "(valor_total_estimado IS NULL OR valor_total_estimado >= 0) AND "
            "(valor_total_homologado IS NULL OR valor_total_homologado >= 0)",
            name="ck_silver_procurement_values",
        ),
        sa.CheckConstraint(
            "data_abertura_proposta IS NULL OR data_encerramento_proposta IS NULL OR "
            "data_encerramento_proposta >= data_abertura_proposta",
            name="ck_silver_procurement_proposal_window",
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_response_id"],
            ["bronze.raw_api_response.id"],
            name="fk_silver_procurement_raw",
        ),
        sa.PrimaryKeyConstraint("numero_controle_pncp"),
        schema="silver",
    )
    op.create_index(
        "ix_silver_procurement_raw",
        "procurement",
        ["source_raw_response_id"],
        schema="silver",
    )
    op.create_index(
        "ix_silver_procurement_orgao",
        "procurement",
        ["orgao_cnpj"],
        schema="silver",
    )
    op.create_index(
        "ix_silver_procurement_updated",
        "procurement",
        ["data_atualizacao_global"],
        schema="silver",
    )

    op.create_table(
        "rejected_record",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_raw_response_id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_index", sa.Integer(), nullable=False),
        sa.Column("natural_key", sa.Text()),
        sa.Column("error_codes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("transformer_version", sa.Text(), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_record_index >= 0", name="ck_silver_rejected_record_index"
        ),
        sa.CheckConstraint(
            "cardinality(error_codes) > 0", name="ck_silver_rejected_error_codes"
        ),
        sa.ForeignKeyConstraint(
            ["source_raw_response_id"],
            ["bronze.raw_api_response.id"],
            name="fk_silver_rejected_raw",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_raw_response_id",
            "source_record_index",
            name="uq_silver_rejected_source_record",
        ),
        schema="silver",
    )
    op.create_index(
        "ix_silver_rejected_raw",
        "rejected_record",
        ["source_raw_response_id"],
        schema="silver",
    )


def downgrade() -> None:
    op.drop_table("rejected_record", schema="silver")
    op.drop_table("procurement", schema="silver")

