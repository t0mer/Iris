"""Per-user dismissal of missing-media warnings, separate from alert read state."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_warning_dismissals",
        sa.Column(
            "alert_id",
            sa.Integer(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_index("ix_media_warning_dismissals_user_id", "media_warning_dismissals", ["user_id"])


def downgrade() -> None:
    op.drop_table("media_warning_dismissals")
