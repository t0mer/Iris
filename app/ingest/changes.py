"""Apply an edit or a delete-for-everyone to a message Iris already holds."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, Job, Message, MessageRevision
from app.openwa.payloads import MessageChange
from app.settings_store import get_setting

NOTIFY_JOB = "notify_change"


async def _notify_parent(db: AsyncSession, message: Message, kind: str) -> None:
    """Queue a WhatsApp follow-up, but only when the parent actually received the alert."""
    if not await get_setting(db, "alerts.notify_changes"):
        return
    alert = (
        await db.execute(
            select(Alert).where(Alert.message_id == message.id, Alert.delivery_status == "sent")
        )
    ).scalar_one_or_none()
    if alert is not None:
        db.add(Job(type=NOTIFY_JOB, payload={"alert_id": alert.id, "kind": kind}))


async def apply_change(db: AsyncSession, change: MessageChange) -> str:
    """Return `edited`, `revoked`, `duplicate` (already applied) or `ignored` (unknown message).

    Matching is by message hash alone, like new messages: a delete reports the sender's own chat
    id, and two monitored sessions both deliver the same change.
    """
    message = (
        await db.execute(select(Message).where(Message.wa_message_id == change.wa_message_id))
    ).scalar_one_or_none()
    if message is None:
        return "ignored"
    now = datetime.now(UTC)

    if change.kind == "revoked":
        if message.revoked_at is not None:
            return "duplicate"
        message.revoked_at = now
        await _notify_parent(db, message, "revoked")
        await db.commit()
        return "revoked"

    new_text = change.new_text
    if new_text is None or new_text == message.text:
        return "duplicate"
    if message.redacted:
        # Withheld content is never copied into history.
        message.edited_at = now
        await db.commit()
        return "edited"
    if message.text:
        db.add(MessageRevision(message_id=message.id, text=message.text, replaced_at=now))
    message.text = new_text
    message.edited_at = now
    # The verdict is kept until the new text is classified, so it can only get worse, not vanish.
    message.status = "pending"
    db.add(Job(type="process_message", payload={"message_id": message.id}))
    await _notify_parent(db, message, "edited")
    await db.commit()
    return "edited"
