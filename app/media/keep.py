"""Keeping a message's media, when the owner turned it on.

Runs after the verdict (and after the redaction decision) is committed, so nothing withheld is
ever stored. A storage problem is logged and counted but never fails classification or an alert.
"""

import asyncio
import hashlib
from pathlib import Path

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.service import should_redact
from app.db.models import Message, StoredMedia
from app.jobs.queue import PermanentError, TransientError
from app.media.factory import build_store
from app.media.fetch import MediaSkipped, fetch_original, job_tmpdir
from app.media.records import mark_purge, stored_for  # noqa: F401
from app.media.sniff import kind_of, sniff_file
from app.media.store import MediaStoreError
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
    db: AsyncSession,
    message: Message,
    categories: list[str],
    key_bytes: bytes,
    data_dir: Path,
    tag: str,
) -> StoredMedia | None:
    """Store the original media if the policy and the safety rules allow it; never raises."""
    try:
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
        logger.warning("media of message {} not kept: {}", message.id, exc.__class__.__name__)
        MEDIA_STORED.labels("-", "failed").inc()
        return None
    except Exception:
        logger.exception("keeping media of message {} failed", message.id)
        MEDIA_STORED.labels("-", "failed").inc()
        return None


async def _store(
    db: AsyncSession, message: Message, kind: str, key_bytes: bytes, data_dir: Path, tag: str
) -> StoredMedia | None:
    store = await build_store(db, key_bytes, data_dir)
    try:
        async with job_tmpdir(data_dir, f"keep-{tag}") as tmp:
            raw = tmp / "media.bin"
            await fetch_original(db, message, key_bytes, raw)
            found = await asyncio.to_thread(sniff_file, raw)
            if found is None:
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
            MEDIA_STORED.labels(store.name, "stored").inc()
            logger.info("media of message {} kept ({}, {} bytes)", message.id, kind, row.size_bytes)
            return row
    finally:
        await store.aclose()
