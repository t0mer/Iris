"""Keep ignored missing-data reports separate from safety judgements."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_data_issues",
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("issue", sa.String(32), nullable=False),
        sa.Column("reported_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_data_issues")
