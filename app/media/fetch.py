"""Per-job temp directory and media download. Media never lives outside {DATA_DIR}/tmp/{job_id}/."""

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Instance, Message
from app.jobs.queue import PermanentError, TransientError
from app.openwa.client import MediaTooLarge, OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.settings_store import get_setting

MAX_MEDIA_BYTES = 25 * 1024 * 1024  # also OpenAI's transcription upload limit
MAX_AUDIO_SECONDS = 15 * 60


class MediaSkipped(Exception):
    """Media that Iris deliberately does not process (too large / too long)."""


@asynccontextmanager
async def job_tmpdir(data_dir: Path, job_id: int | str) -> AsyncIterator[Path]:
    """Temp dir for one job, always removed afterwards (success, failure or cancellation)."""
    path = data_dir / "tmp" / str(job_id)
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
    try:
        yield path
    finally:
        await asyncio.shield(asyncio.to_thread(shutil.rmtree, path, True))


async def download(
    client: OpenWAClient,
    session_id: str,
    chat_id: str,
    message_ref: str,
    dest: Path,
    max_bytes: int | None = None,
) -> str:
    """Download one message's media. Maps OpenWA failures to job error semantics."""
    try:
        return await client.download_media(
            session_id,
            chat_id,
            message_ref,
            dest,
            MAX_MEDIA_BYTES if max_bytes is None else max_bytes,
        )
    except MediaTooLarge as exc:
        raise MediaSkipped(f"media too large ({exc.size} bytes)") from exc
    except OpenWAError as exc:
        if exc.status in (400, 404, 410):  # OpenWA has no copy: retrying cannot help
            raise PermanentError(
                "OpenWA has no stored media for this message (check its inbound media storage)"
            ) from exc
        if exc.status in (401, 403):
            raise PermanentError("OpenWA rejected the API key") from exc
        raise TransientError(f"OpenWA media download failed: {exc.message}") from exc


def media_ref(message: Message) -> dict[str, Any]:
    media = message.media
    if not isinstance(media, dict) or not media.get("message_ref"):
        raise PermanentError("message has no media reference")
    return media


async def openwa_for(
    db: AsyncSession, media: dict[str, Any], key_bytes: bytes
) -> tuple[OpenWAClient, str]:
    instance = await db.get(Instance, media.get("instance_id"))
    if instance is None or not instance.openwa_api_key_enc:
        raise PermanentError("instance or its OpenWA API key is missing")
    client = OpenWAClient(instance.openwa_base_url, decrypt(key_bytes, instance.openwa_api_key_enc))
    return client, instance.openwa_instance_id


def media_refs(message: Message) -> list[dict[str, Any]]:
    """Every OpenWA session's way to fetch this message's media, the first reporter's first.

    A message between two monitored phones is reported by both sessions. OpenWA often keeps the
    media only for one of them (the receiver's copy), so all references are kept as fallbacks.
    """
    primary = media_ref(message)
    alternates = primary.get("alternates")
    extra = [a for a in alternates if isinstance(a, dict)] if isinstance(alternates, list) else []
    return [primary, *[a for a in extra if a.get("message_ref")]]


async def fetch_original(
    db: AsyncSession,
    message: Message,
    key_bytes: bytes,
    dest: Path,
    max_bytes: int | None = None,
    recover: bool = False,
) -> str:
    """Download the message's media, from the session that has it; returns its content type."""
    first_error: PermanentError | None = None
    missing: list[dict[str, Any]] = []
    for ref in media_refs(message):
        try:
            client, session_id = await openwa_for(db, ref, key_bytes)
        except PermanentError as exc:
            first_error = first_error or exc
            continue
        try:
            return await download(
                client, session_id, ref["chat_id"], ref["message_ref"], dest, max_bytes
            )
        except PermanentError as exc:  # this session has no copy: ask the next one
            first_error = first_error or exc
            if recover and "no stored media" in str(exc):
                missing.append(ref)
        finally:
            await client.aclose()
    # Try all already-saved session copies before starting slower WhatsApp recovery.
    attempts = int(await get_setting(db, "media.recovery_attempts")) if missing else 0
    wait = int(await get_setting(db, "media.recovery_wait_seconds")) if missing else 0
    transient: TransientError | None = None
    for ref in missing:
        client, session_id = await openwa_for(db, ref, key_bytes)
        try:
            for attempt in range(attempts):
                if wait:
                    await asyncio.sleep(wait)
                try:
                    return await client.recover_media(
                        session_id,
                        ref["chat_id"],
                        ref["message_ref"],
                        dest,
                        MAX_MEDIA_BYTES if max_bytes is None else max_bytes,
                    )
                except MediaTooLarge as too_large:
                    raise MediaSkipped("Media recovery exceeds its 25 MB limit") from too_large
                except OpenWAError as failure:
                    if failure.status in (400, 404, 410, 501):
                        break  # unsupported engine or WhatsApp no longer has the bytes
                    if failure.status in (401, 403):
                        raise PermanentError("OpenWA rejected the API key") from failure
                    if attempt + 1 == attempts:
                        transient = TransientError("OpenWA media recovery temporarily unavailable")
        finally:
            await client.aclose()
    if transient is not None:
        raise transient
    raise first_error or PermanentError("message has no media reference")
