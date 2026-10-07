"""kept media

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stored_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(255), nullable=False),
        sa.Column("key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("purge", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("message_id", "sha256"),
    )
    op.create_index("ix_stored_media_message_id", "stored_media", ["message_id"])
    op.create_index("ix_stored_media_purge", "stored_media", ["purge"])


def downgrade() -> None:
    op.drop_index("ix_stored_media_purge", table_name="stored_media")
    op.drop_index("ix_stored_media_message_id", table_name="stored_media")
    op.drop_table("stored_media")
