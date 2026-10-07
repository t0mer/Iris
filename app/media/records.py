"""Small queries on kept media that both the alert code and the pipeline need."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StoredMedia


async def stored_for(db: AsyncSession, message_id: int) -> StoredMedia | None:
    """The kept copy that may be shown (not scheduled for deletion)."""
    return (
        await db.execute(
            select(StoredMedia)
            .where(StoredMedia.message_id == message_id, StoredMedia.purge.is_(False))
            .order_by(StoredMedia.id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def mark_purge(db: AsyncSession, message_id: int) -> None:
    """Withheld content must not stay in storage: hide it now, the sweeper deletes the object."""
    await db.execute(
        update(StoredMedia).where(StoredMedia.message_id == message_id).values(purge=True)
    )
