"""Shared predicate for the Home warning and its affected-alerts list."""

from sqlalchemy import ColumnElement, and_, select

from app.db.models import Message, StoredMedia


def missing_media_copy() -> ColumnElement[bool]:
    return and_(
        Message.type.in_(("image", "audio", "voice", "ptt", "video", "sticker", "document")),
        Message.redacted.is_(False),
        Message.id.not_in(select(StoredMedia.message_id).where(StoredMedia.purge.is_(False))),
    )
