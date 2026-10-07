"""/api/media: kept media, shown only to a signed-in owner and always streamed by Iris."""

import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Alert, Message, StoredMedia
from app.deps import get_db
from app.media.factory import MediaOverrides, build_store
from app.media.sniff import INLINE_TYPES
from app.media.store import MediaStore, MediaStoreError
from app.security.auth import current_user

router = APIRouter(prefix="/api/media", tags=["media"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]
Cfg = Annotated[Settings, Depends(get_settings)]
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class MediaOut(BaseModel):
    id: int
    kind: str  # image | audio | video
    content_type: str
    size_bytes: int
    inline: bool  # plays or shows in the browser; otherwise it is offered as a download


def media_out(row: StoredMedia) -> MediaOut:
    return MediaOut(
        id=row.id,
        kind=row.kind,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        inline=row.content_type in INLINE_TYPES,
    )


class MediaInfo(MediaOut):
    message_id: int
    alert_id: int | None


async def _visible(db: AsyncSession, media_id: int) -> StoredMedia:
    """A kept file that may be shown: not scheduled for deletion and its message still shown."""
    row = await db.get(StoredMedia, media_id)
    if row is None or row.purge:
        raise HTTPException(404, "Media not found")
    message = await db.get(Message, row.message_id)
    if message is None or message.redacted:
        raise HTTPException(404, "Media not found")
    return row


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """(start, end) inclusive for a single byte range, None for the whole file."""
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise HTTPException(416, "Invalid range", headers={"Content-Range": f"bytes */{size}"})
    first, last = m.group(1), m.group(2)
    if first == "":  # the last N bytes
        n = min(int(last), size)
        start, end = size - n, size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise HTTPException(
            416, "Range not satisfiable", headers={"Content-Range": f"bytes */{size}"}
        )
    return start, end


@router.get("/{media_id}/info")
async def media_info(media_id: int, db: DB) -> MediaInfo:
    row = await _visible(db, media_id)
    alert_id = (
        await db.execute(select(Alert.id).where(Alert.message_id == row.message_id))
    ).scalar_one_or_none()
    return MediaInfo(**media_out(row).model_dump(), message_id=row.message_id, alert_id=alert_id)


@router.get("/{media_id}")
async def media_file(
    media_id: int,
    db: DB,
    cfg: Cfg,
    range_: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    row = await _visible(db, media_id)
    window = _parse_range(range_, row.size_bytes)
    try:
        store: MediaStore = await build_store(
            db, cfg.key_bytes, cfg.data_dir, MediaOverrides(backend=row.backend)
        )
    except MediaStoreError as exc:
        raise HTTPException(503, "The media storage is not available") from exc

    start, end = window if window else (0, row.size_bytes - 1)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in store.open(row.key, start, end if window else None):
                yield chunk
        except MediaStoreError:
            return  # the connection just ends; the player shows its own error
        finally:
            await store.aclose()

    ext = row.key.rsplit(".", 1)[-1]
    inline = row.content_type in INLINE_TYPES
    headers = {
        "Content-Length": str(end - start + 1),
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        # Even if a file were misjudged, it can run nothing on the portal's origin.
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": (
            "inline" if inline else f'attachment; filename="iris-media-{row.id}.{ext}"'
        ),
    }
    if window:
        headers["Content-Range"] = f"bytes {start}-{end}/{row.size_bytes}"
    return StreamingResponse(
        body(), status_code=206 if window else 200, media_type=row.content_type, headers=headers
    )
