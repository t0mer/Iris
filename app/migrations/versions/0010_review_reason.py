"""Record why a message requires review, and quarantine unexamined legacy media."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("review_reason", sa.String(255)))
    op.add_column("messages", sa.Column("skip_reason", sa.String(255)))
    op.add_column("messages", sa.Column("raw_type", sa.String(255)))
    op.add_column("messages", sa.Column("diagnostics", sa.JSON()))
    op.execute(
        sa.text(
            "UPDATE messages SET skip_reason='Legacy skip; original reason was not recorded' "
            "WHERE status='skipped'"
        )
    )
    op.execute(
        sa.text("""
        UPDATE messages SET verdict='review',
                review_reason='Legacy media has no complete content check'
        WHERE verdict='safe' AND type IN ('image', 'sticker', 'audio', 'voice', 'video')
        AND NOT EXISTS (SELECT 1 FROM review_feedback WHERE message_id=messages.id)
        AND (type='video' OR NOT EXISTS (
            SELECT 1 FROM classifications WHERE message_id=messages.id
            AND (input_kind IN ('image', 'text+image') OR
                 (messages.type IN ('audio', 'voice') AND messages.transcript IS NOT NULL 
                 AND messages.transcript <> ''))
        ))
    """)
    )
    op.execute(
        sa.text("""
        UPDATE messages SET
                review_reason='Legacy review: complete check unavailable or scores inconclusive'
        WHERE verdict='review' AND review_reason IS NULL
    """)
    )


def downgrade() -> None:
    op.drop_column("messages", "diagnostics")
    op.drop_column("messages", "raw_type")
    op.drop_column("messages", "skip_reason")
    op.drop_column("messages", "review_reason")
