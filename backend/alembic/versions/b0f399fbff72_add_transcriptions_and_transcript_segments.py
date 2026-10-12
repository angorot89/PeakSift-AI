"""add transcriptions and transcript segments

Revision ID: b0f399fbff72
Revises: 7092dafdb101
Create Date: 2026-10-12 16:31:37.847104

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0f399fbff72"
down_revision: str | Sequence[str] | None = "7092dafdb101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("video_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("language_probability", sa.Float(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("audio_storage_key", sa.String(length=255), nullable=True),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100", name="ck_transcriptions_progress"
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id"),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transcription_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_transcript_segments_end_after_start"),
        sa.CheckConstraint("start_time >= 0", name="ck_transcript_segments_start_nonnegative"),
        sa.ForeignKeyConstraint(["transcription_id"], ["transcriptions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transcription_id", "sequence_index", name="uq_transcript_segments_order"
        ),
    )
    op.create_index(
        op.f("ix_transcript_segments_transcription_id"),
        "transcript_segments",
        ["transcription_id"],
        unique=False,
    )
    op.create_index(
        "ix_transcript_segments_transcription_start",
        "transcript_segments",
        ["transcription_id", "start_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_segments_transcription_start", table_name="transcript_segments")
    op.drop_index(op.f("ix_transcript_segments_transcription_id"), table_name="transcript_segments")
    op.drop_table("transcript_segments")
    op.drop_table("transcriptions")
