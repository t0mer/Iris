"""Reviewed examples and isolated Ollama comparison runs."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_examples",
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("retrieval_version", sa.String(40), nullable=False),
        sa.Column("baseline_verdict", sa.String(20), nullable=False),
        sa.Column("candidate_verdict", sa.String(20)),
        sa.Column("example_ids", sa.JSON(), nullable=False),
        sa.Column("baseline_scores", sa.JSON(), nullable=False),
        sa.Column("candidate_scores", sa.JSON(none_as_null=True)),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(80)),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_learning_runs_message_id", "learning_runs", ["message_id"])


def downgrade() -> None:
    op.drop_table("learning_runs")
    op.drop_table("learning_examples")
