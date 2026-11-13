"""Approve personal 2FA contacts through expiring confirmation links."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("email_verified", "whatsapp_verified"):
        op.add_column(
            "users", sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    op.drop_column("users", "whatsapp_verified")
    op.drop_column("users", "email_verified")
