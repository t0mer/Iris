"""Deletes kept media that must go: withheld, expired, or whose message was deleted."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Message, StoredMedia
from app.media.factory import build_store, overrides_for
from app.media.store import MediaStore, MediaStoreError
from app.settings_store import get_setting

BATCH = 100


async def sweep_media(
    factory: async_sessionmaker[AsyncSession], key_bytes: bytes, data_dir: Path
) -> int:
    """Flag rows that should go, delete their objects, then the rows. Returns how many went.

    The object is deleted first: if the bucket is unreachable the row stays flagged and the next
    sweep tries again, so nothing is orphaned.
    """
    async with factory() as db:
        days = int(await get_setting(db, "media.retention_days"))
        cutoff = datetime.now(UTC) - timedelta(days=days)
        await db.execute(
            update(StoredMedia).where(StoredMedia.created_at < cutoff).values(purge=True)
        )
        await db.execute(
            update(StoredMedia)
            .where(StoredMedia.message_id.not_in(select(Message.id)))
            .values(purge=True)
        )
        await db.commit()
        rows = list(
            (
                await db.execute(
                    select(StoredMedia)
                    .where(StoredMedia.purge.is_(True))
                    .order_by(StoredMedia.purge_attempts, StoredMedia.id)  # stuck rows go last
                    .limit(BATCH)
                )
            ).scalars()
        )
        removed = 0
        stores: dict[int, MediaStore] = {}
        for row in rows:
            try:
                store = stores.get(row.id)
                if store is None:
                    store = stores[row.id] = await build_store(
                        db, key_bytes, data_dir, overrides_for(row)
                    )
                await store.delete(row.key)
            except MediaStoreError as exc:
                row.purge_attempts += 1
                logger.warning("could not delete kept media {}: {}", row.id, exc)
                continue
            await db.delete(row)
            removed += 1
        await db.commit()
        for store in stores.values():
            await store.aclose()
    if removed:
        logger.info("removed {} kept media files", removed)
    return removed
