"""Per-account alert read state, without attributing old global states to any user."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_views",
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("seen_at", sa.DateTime()),
    )
    op.create_index("ix_alert_views_user_id", "alert_views", ["user_id"])


def downgrade() -> None:
    op.drop_table("alert_views")
