"""Per-child group monitoring exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skipped_groups",
        sa.Column(
            "chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "instance_id",
            sa.Integer(),
            sa.ForeignKey("instances.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("skipped_groups")
