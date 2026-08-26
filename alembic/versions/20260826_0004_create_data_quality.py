"""Create data quality audit tables.

Revision ID: 20260826_0004
Revises: 20260823_0003
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_0004"
down_revision: str | Sequence[str] | None = "20260823_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_quality_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("source_watermark", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_evaluated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Numeric(5, 2)),
        sa.Column("blocking_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.Text()),
        sa.CheckConstraint(
            "rows_evaluated >= 0 AND blocking_failures >= 0",
            name="ck_quality_run_counts",
        ),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100",
            name="ck_quality_run_score",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'FAILED')",
            name="ck_quality_run_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_run"),
        sa.UniqueConstraint("dataset", "source_watermark", name="uq_quality_run_snapshot"),
        schema="control",
    )
    op.create_index(
        "ix_quality_run_status_started",
        "data_quality_run",
        ["status", "started_at"],
        schema="control",
    )
    op.create_table(
        "data_quality_result",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checked_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(5, 2)),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "checked_count >= 0 AND failed_count >= 0 AND failed_count <= checked_count",
            name="ck_quality_result_counts",
        ),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100",
            name="ck_quality_result_score",
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'warning', 'not_evaluated')",
            name="ck_quality_result_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["control.data_quality_run.id"],
            name="fk_quality_result_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quality_result"),
        sa.UniqueConstraint("run_id", "rule_code", name="uq_quality_result_run_rule"),
        schema="control",
    )
    op.create_index(
        "ix_quality_result_rule_status",
        "data_quality_result",
        ["rule_code", "status"],
        schema="control",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quality_result_rule_status",
        table_name="data_quality_result",
        schema="control",
    )
    op.drop_table("data_quality_result", schema="control")
    op.drop_index(
        "ix_quality_run_status_started",
        table_name="data_quality_run",
        schema="control",
    )
    op.drop_table("data_quality_run", schema="control")
