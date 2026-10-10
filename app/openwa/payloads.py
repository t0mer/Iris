"""Normalize OpenWA webhook deliveries into IncomingMessage.

All OpenWA-specific shapes live here (built from real captures in tests/fixtures/openwa/).
Findings that drive the design:
- Only `message.received` and `message.sent` carry new messages. `message.edited` (new text under
  `messageId`) and `message.revoked` (original id under `revokedId`) change a stored message; other
  events are ignored.
- `id` is `<true|false>_<chat>_<hash>[_<author>]`. The hash is identical for the sender and
  receiver, the chat part differs per viewpoint in direct chats (each side sees the other's LID).
- Media is usually `omitted` (only mimetype and size); small files may be inlined as base64.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

MESSAGE_EVENTS = {"message.received", "message.sent"}
CHANGE_EVENTS = {"message.edited", "message.revoked"}
MessageType = Literal[
    "text", "image", "audio", "voice", "video", "sticker", "document", "poll", "other"
]
_KNOWN_TYPES = {"text", "image", "audio", "voice", "video", "sticker", "document", "poll"}


class PayloadError(ValueError):
    """The delivery claims to be a message event but is missing required fields."""


class MediaRef(BaseModel):
    mimetype: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    inline_base64: str | None = None


class MessageChange(BaseModel):
    """An edit or a delete-for-everyone of a message Iris may already hold."""

    kind: Literal["edited", "revoked"]
    wa_message_id: str  # the hash, which matches Message.wa_message_id
    new_text: str | None = None  # edits only: the text after the edit


class IncomingMessage(BaseModel):
    wa_message_id: str  # the hash part, stable across the sender's and receiver's views
    wa_message_ref: str  # the full OpenWA id, needed to download media
    wa_chat_id: str
    chat_name: str | None
    is_group: bool
    sender_wa_id: str | None
    sender_name: str | None  # None for from_me; resolved from the instance's kid name
    from_me: bool
    type: MessageType
    raw_type: str | None = None
    diagnostics: dict[str, bool | str] | None = None
    text: str | None
    media: MediaRef | None
    quoted_wa_message_id: str | None
    sent_at: datetime


def message_hash(wa_id: str) -> str:
    """Extract the stable hash from `<true|false>_<chat>_<hash>[_<author>][_out]`."""
    parts = wa_id.split("_")
    if len(parts) < 3:
        raise PayloadError(f"unrecognised message id: {wa_id!r}")
    return parts[2]


def _quoted_hash(quoted: Any) -> str | None:
    if not isinstance(quoted, dict) or not isinstance(quoted.get("id"), str):
        return None
    try:
        return message_hash(quoted["id"])
    except PayloadError:
        return None


def _media(data: dict[str, Any]) -> MediaRef | None:
    m = data.get("media")
    if not isinstance(m, dict):
        return None
    return MediaRef(
        mimetype=m.get("mimetype"),
        filename=m.get("filename"),
        size_bytes=m.get("sizeBytes"),
        inline_base64=m.get("data") if isinstance(m.get("data"), str) else None,
    )


def poll_text(data: dict[str, Any]) -> tuple[str | None, bool]:
    """Preserve the supplied question/options as analyzable text; never infer poll contents."""
    poll = data.get("poll")
    body = data.get("body")
    text = body if isinstance(body, str) and body else None
    if not isinstance(poll, dict):
        return text, False
    question = poll.get("question")
    if isinstance(question, str) and question:
        text = question
    options = poll.get("options")
    if not isinstance(options, list) or not options:
        return text, False
    names = [
        option
        if isinstance(option, str)
        else option.get("name")
        if isinstance(option, dict)
        else None
        for option in options
    ]
    if not all(isinstance(name, str) and name.strip() for name in names):
        raise PayloadError("Invalid poll options")
    lines = [text] if text else []
    lines.extend("• " + str(name) for name in names)
    if isinstance(poll.get("allowMultipleAnswers"), bool):
        lines.append("Multiple answers: " + ("yes" if poll["allowMultipleAnswers"] else "no"))
    return "\n".join(lines), True


def parse_event(body: dict[str, Any]) -> IncomingMessage | None:
    """Return the message for message events, or None for events Iris ignores."""
    if body.get("event") not in MESSAGE_EVENTS:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        raise PayloadError("message event without data")
    try:
        wa_id: str = data["id"]
        chat_id: str = data["chatId"]
        ts = int(data["timestamp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PayloadError(f"missing field: {exc}") from exc
    if data.get("isStatusBroadcast") or chat_id == "status@broadcast":
        return None

    from_me = bool(data.get("fromMe"))
    is_group = bool(data.get("isGroup"))
    raw_contact = data.get("contact")
    contact: dict[str, Any] = raw_contact if isinstance(raw_contact, dict) else {}
    # Sender name resolution: push name, then contact name, then the sender id.
    sender_id = data.get("author") if is_group and data.get("author") else data.get("from")
    sender_name = None if from_me else (contact.get("pushName") or contact.get("name") or sender_id)
    raw_type = data.get("type")
    normalized_type = (
        {"chat": "text", "ptt": "voice", "poll_creation": "poll"}.get(raw_type, raw_type)
        if isinstance(raw_type, str)
        else None
    )
    quoted = data.get("quotedMessage")
    text, has_poll_options = (
        poll_text(data) if normalized_type == "poll" else (data.get("body") or None, False)
    )
    diagnostics: dict[str, bool | str] = {
        "event": str(body["event"]),
        "has_text": bool(text),
        "has_media": isinstance(data.get("media"), dict),
        "has_quoted_message": isinstance(quoted, dict),
    }
    if has_poll_options:
        diagnostics["has_poll_options"] = True

    return IncomingMessage(
        wa_message_id=message_hash(wa_id),
        wa_message_ref=wa_id,
        wa_chat_id=chat_id,
        chat_name=None,  # not in the payload; groups are named later via the OpenWA API
        is_group=is_group,
        sender_wa_id=sender_id,
        sender_name=sender_name,
        from_me=from_me,
        type=normalized_type if normalized_type in _KNOWN_TYPES else "other",
        raw_type=raw_type[:255] if isinstance(raw_type, str) else None,
        diagnostics=diagnostics,
        text=text,
        media=_media(data),
        quoted_wa_message_id=_quoted_hash(quoted),
        sent_at=datetime.fromtimestamp(ts, tz=UTC),
    )


def parse_change(body: dict[str, Any]) -> MessageChange | None:
    """Return the change for `message.edited` / `message.revoked`, or None for any other event."""
    event = body.get("event")
    if event not in CHANGE_EVENTS:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        raise PayloadError("message event without data")
    key = "messageId" if event == "message.edited" else "revokedId"
    wa_id = data.get(key)
    if not isinstance(wa_id, str):
        raise PayloadError(f"missing field: {key}")
    if event == "message.revoked":
        return MessageChange(kind="revoked", wa_message_id=message_hash(wa_id))
    text = data.get("body")
    return MessageChange(
        kind="edited",
        wa_message_id=message_hash(wa_id),
        new_text=text if isinstance(text, str) else None,
    )
