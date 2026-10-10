"""Persist each user's interface language independently of their browser."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("language", sa.String(32), nullable=False, server_default="system")
    )


def downgrade() -> None:
    op.drop_column("users", "language")
