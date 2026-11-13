"""Persist sending budgets across workers and restarts."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sending_budgets",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("next_allowed", UTCDateTime(), nullable=False),
        sa.Column("hour_start", UTCDateTime(), nullable=False),
        sa.Column("hour_count", sa.Integer(), nullable=False),
        sa.Column("day_start", UTCDateTime(), nullable=False),
        sa.Column("day_count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sending_budgets")
