"""Record retrieval strategy, embedding model, and fallback provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learning_runs", sa.Column("retrieval", sa.JSON(none_as_null=True)))


def downgrade() -> None:
    op.drop_column("learning_runs", "retrieval")
