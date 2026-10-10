"""User roles, contacts and single-use login challenges."""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="admin"))
    op.add_column("users", sa.Column("email", sa.String(255)))
    op.add_column("users", sa.Column("phone_instance_id", sa.Integer()))
    op.add_column(
        "users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "login_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )

    op.create_table(
        "review_feedback",
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("reviewed_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("review_feedback")
    op.drop_table("login_challenges")
    for column in ("auth_version", "phone_instance_id", "email", "role"):
        op.drop_column("users", column)
