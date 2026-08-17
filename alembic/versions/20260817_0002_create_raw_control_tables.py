"""Create RAW and ingestion control tables.

Revision ID: 20260817_0002
Revises: 20260817_0001
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260817_0002"
down_revision: str | Sequence[str] | None = "20260817_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATASET_CHECK = "dataset IN ('procurements', 'contracts')"
MODE_CHECK = "mode IN ('publicacao', 'atualizacao')"
LOWERCASE_SHA256_CHECK = "VALUE ~ '^[0-9a-f]{64}$'"


def upgrade() -> None:
    op.create_table(
        "etl_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("records_received", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("records_inserted", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("records_duplicate", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.CheckConstraint(DATASET_CHECK, name="ck_etl_run_dataset"),
        sa.CheckConstraint(MODE_CHECK, name="ck_etl_run_mode"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_etl_run_status",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND finished_at IS NULL) OR "
            "(status IN ('SUCCEEDED', 'FAILED') AND finished_at IS NOT NULL)",
            name="ck_etl_run_terminal_time",
        ),
        sa.CheckConstraint(
            "pages_processed >= 0",
            name="ck_etl_run_pages_processed_non_negative",
        ),
        sa.CheckConstraint(
            "records_received >= 0",
            name="ck_etl_run_records_received_non_negative",
        ),
        sa.CheckConstraint(
            "records_inserted >= 0",
            name="ck_etl_run_records_inserted_non_negative",
        ),
        sa.CheckConstraint(
            "records_duplicate >= 0",
            name="ck_etl_run_records_duplicate_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="control",
    )

    op.create_table(
        "extraction_checkpoint",
        sa.Column("scope_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("scope_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_successful_page", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(DATASET_CHECK, name="ck_extraction_checkpoint_dataset"),
        sa.CheckConstraint(MODE_CHECK, name="ck_extraction_checkpoint_mode"),
        sa.CheckConstraint(
            LOWERCASE_SHA256_CHECK.replace("VALUE", "scope_fingerprint"),
            name="ck_extraction_checkpoint_scope_fingerprint",
        ),
        sa.CheckConstraint(
            "last_successful_page > 0",
            name="ck_extraction_checkpoint_last_successful_page_positive",
        ),
        sa.PrimaryKeyConstraint("scope_fingerprint"),
        schema="control",
    )

    op.create_table(
        "etl_watermark",
        sa.Column("pipeline_name", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("watermark_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(DATASET_CHECK, name="ck_etl_watermark_dataset"),
        sa.PrimaryKeyConstraint("pipeline_name", "dataset", "stage"),
        schema="control",
    )

    op.create_table(
        "raw_api_response",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("etl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("request_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=False),
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.CheckConstraint(DATASET_CHECK, name="ck_raw_response_dataset"),
        sa.CheckConstraint(
            LOWERCASE_SHA256_CHECK.replace("VALUE", "request_fingerprint"),
            name="ck_raw_response_request_fingerprint",
        ),
        sa.CheckConstraint(
            LOWERCASE_SHA256_CHECK.replace("VALUE", "body_sha256"),
            name="ck_raw_response_body_sha256",
        ),
        sa.CheckConstraint("window_end >= window_start", name="ck_raw_response_window"),
        sa.CheckConstraint("page_number > 0", name="ck_raw_response_page_number_positive"),
        sa.CheckConstraint(
            "http_status BETWEEN 200 AND 299",
            name="ck_raw_response_http_status",
        ),
        sa.CheckConstraint(
            "record_count >= 0",
            name="ck_raw_response_record_count_non_negative",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_raw_response_duration_ms_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["etl_run_id"],
            ["control.etl_run.id"],
            name="fk_raw_response_etl_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "dataset",
            "endpoint",
            "request_fingerprint",
            "body_sha256",
            name="uq_raw_response_identity_body",
        ),
        schema="bronze",
    )
    op.create_index(
        "ix_raw_response_dataset_collected_at",
        "raw_api_response",
        ["dataset", "collected_at"],
        unique=False,
        schema="bronze",
    )


def downgrade() -> None:
    op.drop_table("raw_api_response", schema="bronze")
    op.drop_table("etl_watermark", schema="control")
    op.drop_table("extraction_checkpoint", schema="control")
    op.drop_table("etl_run", schema="control")
