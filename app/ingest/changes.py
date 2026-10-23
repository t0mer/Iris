"""Apply an edit or a delete-for-everyone to a message Iris already holds."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, Job, Message, MessageRevision
from app.openwa.payloads import MessageChange
from app.settings_store import get_setting

NOTIFY_JOB = "notify_change"
# A redelivered older edit arrives within moments of the newer one; a real edit back to the
# previous wording is slower than this.
REDELIVERY_WINDOW = timedelta(minutes=2)


async def _notify_parent(db: AsyncSession, message: Message, kind: str) -> None:
    """Queue a WhatsApp follow-up for an alert that is delivered or still being delivered.

    The job itself waits for a pending delivery and drops out if the alert never reached the
    parent. A burst of edits shares one queued follow-up.
    """
    if not await get_setting(db, "alerts.notify_changes"):
        return
    alert = (
        await db.execute(
            select(Alert).where(
                Alert.message_id == message.id,
                Alert.delivery_status.in_(("pending", "sent", "partial")),
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        return
    queued = (
        await db.execute(
            select(Job.id).where(
                Job.type == NOTIFY_JOB,
                Job.status.in_(("queued", "running")),
                Job.payload["alert_id"].as_integer() == alert.id,
                Job.payload["kind"].as_string() == kind,
            )
        )
    ).first()
    if queued is None:
        db.add(Job(type=NOTIFY_JOB, payload={"alert_id": alert.id, "kind": kind}))


async def apply_change(db: AsyncSession, change: MessageChange) -> str:
    """Return `edited`, `revoked`, `duplicate` (already applied) or `ignored` (unknown message).

    Matching is by message hash alone, like new messages: a delete reports the sender's own chat
    id, and two monitored sessions both deliver the same change.
    """
    message = (
        await db.execute(
            select(Message).where(Message.wa_message_id == change.wa_message_id).limit(1)
        )
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

    if message.revoked_at is not None:
        return "ignored"

    new_text = change.new_text
    if new_text is None or new_text == message.text:
        return "duplicate"
    last = (
        await db.execute(
            select(MessageRevision)
            .where(MessageRevision.message_id == message.id)
            .order_by(MessageRevision.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if (
        last is not None
        and last.text == new_text
        and message.edited_at is not None
        and _aware(message.edited_at) > now - REDELIVERY_WINDOW
    ):
        return "duplicate"  # an older edit delivered again after a newer one
    old_text = message.text
    # The classifier may withhold this message at any moment, so the change is conditional on it
    # still being unredacted; the write lock held from here to the commit keeps it that way.
    res = await db.execute(
        update(Message)
        .where(Message.id == message.id, Message.redacted.is_(False), Message.revoked_at.is_(None))
        .values(text=new_text, edited_at=now, status="pending")
        .execution_options(synchronize_session=False)
    )
    if res.rowcount == 0:  # type: ignore[attr-defined]
        # Withheld content is never copied into history.
        await db.execute(update(Message).where(Message.id == message.id).values(edited_at=now))
        await db.commit()
        return "edited"
    if old_text:
        db.add(MessageRevision(message_id=message.id, text=old_text, replaced_at=now))
    # The verdict is kept until the new text is classified, so it can only get worse, not vanish.
    db.add(Job(type="process_message", payload={"message_id": message.id}))
    await _notify_parent(db, message, "edited")
    await db.commit()
    return "edited"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
