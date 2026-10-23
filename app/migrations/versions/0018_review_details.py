"""Optional human categories and explanations bound to reviewed content."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_feedback", sa.Column("categories", sa.JSON(none_as_null=True)))
    op.add_column("review_feedback", sa.Column("explanation", sa.Text()))
    op.add_column("review_feedback", sa.Column("content_hash", sa.String(64)))


def downgrade() -> None:
    for column in ("content_hash", "explanation", "categories"):
        op.drop_column("review_feedback", column)
