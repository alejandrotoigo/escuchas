"""Initial schema

Revision ID: 20260422_0001
Revises:
Create Date: 2026-04-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260422_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaign_name"), "campaign", ["name"], unique=False)

    op.create_table(
        "stream",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stream_name"), "stream", ["name"], unique=False)

    op.create_table(
        "ad",
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("normalized_audio_path", sa.String(), nullable=True),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column("processing_status", sa.String(), nullable=False),
        sa.Column("processing_error", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaign.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ad_campaign_id"), "ad", ["campaign_id"], unique=False)

    op.create_table(
        "detection",
        sa.Column("ad_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("offset_seconds", sa.Float(), nullable=True),
        sa.Column("evidence_path", sa.String(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ad_id"], ["ad.id"]),
        sa.ForeignKeyConstraint(["stream_id"], ["stream.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_detection_ad_id"), "detection", ["ad_id"], unique=False)
    op.create_index(op.f("ix_detection_stream_id"), "detection", ["stream_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_detection_stream_id"), table_name="detection")
    op.drop_index(op.f("ix_detection_ad_id"), table_name="detection")
    op.drop_table("detection")
    op.drop_index(op.f("ix_ad_campaign_id"), table_name="ad")
    op.drop_table("ad")
    op.drop_index(op.f("ix_stream_name"), table_name="stream")
    op.drop_table("stream")
    op.drop_index(op.f("ix_campaign_name"), table_name="campaign")
    op.drop_table("campaign")