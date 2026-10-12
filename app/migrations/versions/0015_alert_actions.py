"""Recipient-bound review buttons and parent response notes."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_actions",
        sa.Column("token", sa.String(48), primary_key=True),
        sa.Column(
            "alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("destination", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("choice", sa.String(20), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_alert_actions_alert_id", "alert_actions", ["alert_id"])
    op.create_table(
        "review_responses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("choice", sa.String(20), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_review_responses_message_id", "review_responses", ["message_id"])


def downgrade() -> None:
    op.drop_table("review_responses")
    op.drop_table("alert_actions")
