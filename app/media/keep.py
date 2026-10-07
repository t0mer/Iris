"""Keeping a message's media, when the owner turned it on.

Runs after the verdict (and after the redaction decision) is committed, so nothing withheld is
ever stored. It works in its own database session: a storage or database problem here can never
leave the caller's session broken, so classification and the alert are never lost to it.
"""

import asyncio
import hashlib
from pathlib import Path

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.service import should_redact
from app.db.models import Message, StoredMedia
from app.jobs.queue import PermanentError, TransientError
from app.media.factory import build_store
from app.media.fetch import MediaSkipped, fetch_original, job_tmpdir
from app.media.records import mark_purge, stored_for  # noqa: F401
from app.media.sniff import kind_of, matches_kind, sniff_file
from app.media.store import MediaStore, MediaStoreError
from app.metrics import MEDIA_STORED
from app.settings_store import get_setting

# Which verdicts each policy keeps (a verdict of None, a failed or skipped check, is never kept).
KEEPS: dict[str, set[str]] = {
    "harmful": {"harmful"},
    "harmful_review": {"harmful", "review"},
    "all": {"harmful", "review", "safe"},
}


def wants(policy: str, verdict: str | None) -> bool:
    return verdict is not None and verdict in KEEPS.get(policy, set())


async def keep_media(
    factory: async_sessionmaker[AsyncSession],
    message_id: int,
    categories: list[str],
    key_bytes: bytes,
    data_dir: Path,
    tag: str,
    examined: bool = True,
) -> StoredMedia | None:
    """Store the original media if the policy and the safety rules allow it; never raises.

    `categories` are everything the check flagged, over all stages. `examined` is false when the
    media itself could not be checked (conversion or transcription failed): it is then not kept.
    """
    try:
        async with factory() as db:
            message = await db.get(Message, message_id)
            if message is None or not examined:
                return None
            policy = str(await get_setting(db, "media.policy"))
            kind = kind_of(message.type)
            if policy == "off" or kind is None or not wants(policy, message.verdict):
                return None
            if message.redacted or should_redact(message.type, categories):
                return None  # withheld content is never kept, whatever the policy
            if await stored_for(db, message.id) is not None:
                return None  # a retry or a re-check: the media never changes
            return await _store(db, message, kind, key_bytes, data_dir, tag)
    except (MediaStoreError, MediaSkipped, PermanentError, TransientError, OSError) as exc:
        logger.warning("media of message {} not kept: {}", message_id, exc.__class__.__name__)
        MEDIA_STORED.labels("-", "failed").inc()
    except Exception:
        logger.exception("keeping media of message {} failed", message_id)
        MEDIA_STORED.labels("-", "failed").inc()
    return None


async def _store(
    db: AsyncSession, message: Message, kind: str, key_bytes: bytes, data_dir: Path, tag: str
) -> StoredMedia | None:
    store = await build_store(db, key_bytes, data_dir)
    key: str | None = None
    saved = False
    try:
        async with job_tmpdir(data_dir, f"keep-{tag}") as tmp:
            raw = tmp / "media.bin"
            await fetch_original(db, message, key_bytes, raw)
            found = await asyncio.to_thread(sniff_file, raw)
            if found is None or not matches_kind(kind, found[0]):
                logger.info("media of message {} is not a keepable format", message.id)
                MEDIA_STORED.labels(store.name, "skipped").inc()
                return None
            content_type, ext, _inline = found
            digest = await asyncio.to_thread(lambda: hashlib.sha256(raw.read_bytes()).hexdigest())
            key = f"media/{message.id}/{digest[:16]}.{ext}"
            await store.put(key, raw, content_type)
            row = StoredMedia(
                message_id=message.id,
                backend=store.name,
                location=store.location,
                key=key,
                content_type=content_type,
                kind=kind,
                size_bytes=raw.stat().st_size,
                sha256=digest,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:  # another job stored the same bytes a moment ago
                await db.rollback()
                return await stored_for(db, message.id)
            saved = True
        # Withheld while the file was downloading (a review resolved, a second check): the
        # row exists now, so flag it; the sweeper deletes the object within a minute.
        await db.refresh(message)
        if message.redacted:
            row.purge = True
            await db.commit()
            MEDIA_STORED.labels(store.name, "skipped").inc()
            return None
        MEDIA_STORED.labels(store.name, "stored").inc()
        logger.info("media of message {} kept ({}, {} bytes)", message.id, kind, row.size_bytes)
        return row
    finally:
        if key is not None and not saved:
            await _forget(store, key)  # uploaded but not recorded: do not leave an orphan
        await store.aclose()


async def _forget(store: MediaStore, key: str) -> None:
    try:
        await store.delete(key)
    except MediaStoreError:
        logger.warning("could not remove an unrecorded media file")
