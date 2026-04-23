"""Add persistent monitor jobs

Revision ID: 20260422_0002
Revises: 20260422_0001
Create Date: 2026-04-22 00:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260422_0002"
down_revision = "20260422_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_job",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("stream_name", sa.String(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=True),
        sa.Column("run_forever", sa.Boolean(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("window_step_seconds", sa.Float(), nullable=False),
        sa.Column("pause_between_windows_seconds", sa.Float(), nullable=False),
        sa.Column("similarity_threshold", sa.Float(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("keep_evidence", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_iterations", sa.Integer(), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("total_detections_created", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"]),
        sa.ForeignKeyConstraint(["stream_id"], ["stream.id"]),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(op.f("ix_monitor_job_campaign_id"), "monitor_job", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_monitor_job_status"), "monitor_job", ["status"], unique=False)
    op.create_index(op.f("ix_monitor_job_stream_id"), "monitor_job", ["stream_id"], unique=False)

    op.create_table(
        "monitor_job_iteration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matches_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["monitor_job.job_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "iteration", name="uq_monitor_job_iteration_job_iteration"),
    )
    op.create_index(op.f("ix_monitor_job_iteration_iteration"), "monitor_job_iteration", ["iteration"], unique=False)
    op.create_index(op.f("ix_monitor_job_iteration_job_id"), "monitor_job_iteration", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_monitor_job_iteration_job_id"), table_name="monitor_job_iteration")
    op.drop_index(op.f("ix_monitor_job_iteration_iteration"), table_name="monitor_job_iteration")
    op.drop_table("monitor_job_iteration")
    op.drop_index(op.f("ix_monitor_job_stream_id"), table_name="monitor_job")
    op.drop_index(op.f("ix_monitor_job_status"), table_name="monitor_job")
    op.drop_index(op.f("ix_monitor_job_campaign_id"), table_name="monitor_job")
    op.drop_table("monitor_job")