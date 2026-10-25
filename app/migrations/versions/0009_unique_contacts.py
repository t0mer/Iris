"""Reserve normalized contacts without deleting any legacy duplicate contacts."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_contact_key", sa.String(255)))
    op.add_column("users", sa.Column("whatsapp_contact_key", sa.String(16)))
    # Set-based SQL works for online execution and offline SQL generation on all supported DBs.
    op.execute(
        sa.text("""
        UPDATE users SET email_contact_key = LOWER(TRIM(email))
        WHERE email IS NOT NULL AND TRIM(email) <> '' AND id IN (
            SELECT first_id FROM (
                SELECT MIN(id) AS first_id FROM users
                WHERE email IS NOT NULL AND TRIM(email) <> ''
                GROUP BY LOWER(TRIM(email))
            ) AS owners
        )
    """)
    )
    op.execute(
        sa.text("""
        UPDATE users SET whatsapp_contact_key = TRIM(whatsapp_number)
        WHERE whatsapp_number IS NOT NULL AND TRIM(whatsapp_number) <> '' AND id IN (
            SELECT first_id FROM (
                SELECT MIN(id) AS first_id FROM users
                WHERE whatsapp_number IS NOT NULL AND TRIM(whatsapp_number) <> ''
                GROUP BY TRIM(whatsapp_number)
            ) AS owners
        )
    """)
    )
    op.create_index("uq_users_email_contact_key", "users", ["email_contact_key"], unique=True)
    op.create_index("uq_users_whatsapp_contact_key", "users", ["whatsapp_contact_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_email_contact_key", table_name="users")
    op.drop_index("uq_users_whatsapp_contact_key", table_name="users")
    op.drop_column("users", "email_contact_key")
    op.drop_column("users", "whatsapp_contact_key")
