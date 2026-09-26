# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2025-2026 Afeef Janjua
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "m1n2o3p4q5r6"
down_revision: Union[str, None] = "l0m1n2o3p4q5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meeting",
        sa.Column("transcript_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "meeting",
        sa.Column("derived_transcript_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "transcriptsegment",
        sa.Column("text_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "transcriptsegment",
        sa.Column("word_alignment_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "meetingspeaker",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meeting.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("speaker_key", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "meeting_id",
            "speaker_key",
            name="uq_meetingspeaker_meeting_key",
        ),
    )
    op.create_index("ix_meetingspeaker_meeting_id", "meetingspeaker", ["meeting_id"])

    op.create_table(
        "transcripteditjob",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meeting.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(instruction) <= 4000",
            name="ck_transcripteditjob_instruction_length",
        ),
    )
    op.create_index("ix_transcripteditjob_meeting_id", "transcripteditjob", ["meeting_id"])
    op.create_index("ix_transcripteditjob_requested_by", "transcripteditjob", ["requested_by"])
    op.create_index("ix_transcripteditjob_status", "transcripteditjob", ["status"])
    op.create_index("ix_transcripteditjob_created_at", "transcripteditjob", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_transcripteditjob_created_at", table_name="transcripteditjob")
    op.drop_index("ix_transcripteditjob_status", table_name="transcripteditjob")
    op.drop_index("ix_transcripteditjob_requested_by", table_name="transcripteditjob")
    op.drop_index("ix_transcripteditjob_meeting_id", table_name="transcripteditjob")
    op.drop_table("transcripteditjob")
    op.drop_index("ix_meetingspeaker_meeting_id", table_name="meetingspeaker")
    op.drop_table("meetingspeaker")
    op.drop_column("transcriptsegment", "word_alignment_valid")
    op.drop_column("transcriptsegment", "text_edited")
    op.drop_column("meeting", "derived_transcript_revision")
    op.drop_column("meeting", "transcript_revision")
