import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from govinsight.raw.tables import metadata

data_quality_run = sa.Table(
    "data_quality_run",
    metadata,
    sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
    sa.Column("dataset", sa.Text(), nullable=False),
    sa.Column("stage", sa.Text(), nullable=False),
    sa.Column("source_watermark", sa.BigInteger(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("rows_evaluated", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("score", sa.Numeric(5, 2)),
    sa.Column("blocking_failures", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("error_code", sa.Text()),
    sa.PrimaryKeyConstraint("id", name="pk_quality_run"),
    sa.UniqueConstraint("dataset", "source_watermark", name="uq_quality_run_snapshot"),
    sa.CheckConstraint(
        "status IN ('RUNNING', 'PASSED', 'FAILED')",
        name="ck_quality_run_status",
    ),
    sa.CheckConstraint(
        "score IS NULL OR score BETWEEN 0 AND 100",
        name="ck_quality_run_score",
    ),
    sa.CheckConstraint(
        "rows_evaluated >= 0 AND blocking_failures >= 0",
        name="ck_quality_run_counts",
    ),
    sa.Index("ix_quality_run_status_started", "status", "started_at"),
    schema="control",
)

data_quality_result = sa.Table(
    "data_quality_result",
    metadata,
    sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
    sa.Column(
        "run_id",
        sa.BigInteger(),
        sa.ForeignKey(
            "control.data_quality_run.id",
            name="fk_quality_result_run",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    sa.Column("rule_code", sa.Text(), nullable=False),
    sa.Column("dimension", sa.Text(), nullable=False),
    sa.Column("severity", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("checked_count", sa.Integer(), nullable=False),
    sa.Column("failed_count", sa.Integer(), nullable=False),
    sa.Column("score", sa.Numeric(5, 2)),
    sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id", name="pk_quality_result"),
    sa.UniqueConstraint("run_id", "rule_code", name="uq_quality_result_run_rule"),
    sa.CheckConstraint(
        "status IN ('passed', 'failed', 'warning', 'not_evaluated')",
        name="ck_quality_result_status",
    ),
    sa.CheckConstraint(
        "score IS NULL OR score BETWEEN 0 AND 100",
        name="ck_quality_result_score",
    ),
    sa.CheckConstraint(
        "checked_count >= 0 AND failed_count >= 0 AND failed_count <= checked_count",
        name="ck_quality_result_counts",
    ),
    sa.Index("ix_quality_result_rule_status", "rule_code", "status"),
    schema="control",
)

__all__ = ["data_quality_result", "data_quality_run"]
