"""Personal WhatsApp 2FA recipients independent of OpenWA sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("whatsapp_number", sa.String(16)))
    # Session assignments cannot identify a user's personal number. Require explicit entry.
    op.execute(
        "UPDATE users SET auth_version = auth_version + 1 WHERE phone_instance_id IS NOT NULL"
    )
    op.execute("UPDATE users SET phone_instance_id = NULL")


def downgrade() -> None:
    op.drop_column("users", "whatsapp_number")
