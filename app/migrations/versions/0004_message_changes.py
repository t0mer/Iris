"""message edits and revokes

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("edited_at", UTCDateTime(), nullable=True))
    op.add_column("messages", sa.Column("revoked_at", UTCDateTime(), nullable=True))
    op.create_table(
        "message_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("replaced_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_message_revisions_message_id", "message_revisions", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_revisions_message_id", table_name="message_revisions")
    op.drop_table("message_revisions")
    op.drop_column("messages", "revoked_at")
    op.drop_column("messages", "edited_at")
