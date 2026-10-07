"""deliver_alert job: send one alert over WhatsApp via the configured sender instance."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import Select, func, select

from app.alerts.format import AlertFacts, MediaFact, format_alert, format_change_notice
from app.db.models import Alert, Chat, Instance, Message, StoredMedia
from app.jobs.queue import ClaimedJob, PermanentError, TransientError
from app.media.records import stored_for
from app.metrics import ALERTS
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.settings_store import get_setting

if TYPE_CHECKING:
    from app.jobs.handlers import Deps


def recipient_chat_id(recipient: str) -> str:
    """A phone number (digits, optional +) becomes `<digits>@c.us`; chat ids pass through."""
    r = recipient.strip()
    return r if "@" in r else f"{r.lstrip('+')}@c.us"


def _top(alert: Alert) -> str:
    return alert.categories[0] if alert.categories else "unknown"


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _chat_alerts(chat_id: int, alert_id: int) -> "Select[Any]":
    """Other alerts in the same chat."""
    return (
        select(Alert)
        .join(Message, Message.id == Alert.message_id)
        .where(Message.chat_id == chat_id, Alert.id != alert_id)
    )


def build_facts(
    alert: Alert,
    message: Message,
    chat: Chat | None,
    more_suppressed: int = 0,
    media: StoredMedia | None = None,
) -> AlertFacts:
    return AlertFacts(
        alert_id=alert.id,
        kid_names=list(alert.kid_names),
        chat_name=alert.chat_name,
        is_group=bool(chat and chat.is_group),
        sender_name=alert.sender_name,
        from_me=message.from_me,
        categories=list(alert.categories) or ["?"],
        max_score=alert.max_score,
        sent_at=message.sent_at,
        quote=alert.quote,
        more_suppressed=more_suppressed,
        media=(
            MediaFact(media.id, media.kind, media.size_bytes)
            if media is not None and not message.redacted
            else None
        ),
    )


# One process, one delivery decision at a time: the cooldown check and the send must not
# interleave across workers, or two alerts in one chat would both go out.
_DELIVERY_LOCK = asyncio.Lock()


async def deliver_alert(job: ClaimedJob, deps: "Deps") -> None:
    async with _DELIVERY_LOCK:
        await _deliver(job, deps)


async def _deliver(job: ClaimedJob, deps: "Deps") -> None:
    alert_id = job.payload.get("alert_id")
    force = bool(job.payload.get("force"))  # manual resend ignores the cooldown
    if not isinstance(alert_id, int):
        raise PermanentError("job payload has no alert_id")
    async with deps.session_factory() as db:
        alert = await db.get(Alert, alert_id)
        if alert is None:
            raise PermanentError("alert no longer exists")
        if alert.delivery_status == "sent" and not force:
            return
        message = await db.get(Message, alert.message_id)
        if message is None:
            raise PermanentError("alert's message no longer exists")
        chat = await db.get(Chat, message.chat_id)

        sender_id = await get_setting(db, "alerts.sender_instance_id")
        recipient = await get_setting(db, "alerts.recipient")
        sender = await db.get(Instance, sender_id) if sender_id else None
        if not recipient or sender is None or not sender.openwa_api_key_enc:
            alert.delivery_status, alert.delivery_error = "failed", "alert delivery not configured"
            await db.commit()
            raise PermanentError("alert delivery not configured")

        more = 0
        last_sent = (
            await db.scalars(
                _chat_alerts(message.chat_id, alert.id)
                .where(Alert.notified_at.is_not(None))
                .order_by(Alert.notified_at.desc())
                .limit(1)
            )
        ).first()
        if last_sent is not None and last_sent.notified_at is not None:
            cooldown = int(await get_setting(db, "alerts.cooldown_minutes"))
            window_start = _naive_utc(datetime.now(UTC)) - timedelta(minutes=cooldown)
            if not force and _naive_utc(last_sent.notified_at) >= window_start:
                alert.delivery_status, alert.delivery_error = "suppressed", None
                await db.commit()
                ALERTS.labels(_top(alert), "suppressed").inc()
                logger.info("alert {} suppressed by the chat cooldown", alert.id)
                return
            more = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(Alert)
                        .join(Message, Message.id == Alert.message_id)
                        .where(
                            Message.chat_id == message.chat_id,
                            Alert.id != alert.id,
                            Alert.delivery_status == "suppressed",
                            Alert.created_at > last_sent.notified_at,
                        )
                    )
                ).scalar_one()
            )

        timezone = str(await get_setting(db, "alerts.timezone"))
        facts = build_facts(
            alert, message, chat, more_suppressed=more, media=await stored_for(db, message.id)
        )
        text = format_alert(facts, timezone, deps.public_base_url, deps.key_bytes)
        client = OpenWAClient(
            sender.openwa_base_url, decrypt(deps.key_bytes, sender.openwa_api_key_enc)
        )
        try:
            await client.send_text(sender.openwa_instance_id, recipient_chat_id(recipient), text)
        except OpenWAError as exc:
            if exc.status is None or exc.status >= 500 or exc.status == 429:
                raise TransientError(f"alert delivery failed: {exc.message}") from exc
            alert.delivery_status, alert.delivery_error = "failed", exc.message[:300]
            await db.commit()
            raise PermanentError(f"alert delivery rejected: {exc.message}") from exc
        finally:
            await client.aclose()
        alert.delivery_status, alert.delivery_error = "sent", None
        alert.notified_at = datetime.now(UTC)
        await db.commit()
        ALERTS.labels(_top(alert), "sent").inc()
        logger.info("alert {} delivered", alert.id)


async def notify_change(job: ClaimedJob, deps: "Deps") -> None:
    """Tell the parent that the message of an already delivered alert was edited or deleted."""
    alert_id, kind = job.payload.get("alert_id"), job.payload.get("kind")
    if not isinstance(alert_id, int) or kind not in ("edited", "revoked"):
        raise PermanentError("job payload has no alert_id or kind")
    async with _DELIVERY_LOCK, deps.session_factory() as db:
        alert = await db.get(Alert, alert_id)
        if alert is None:
            raise PermanentError("alert no longer exists")
        if alert.delivery_status == "pending":
            raise TransientError("the alert itself is not delivered yet")
        if alert.delivery_status != "sent":
            logger.info("alert {} never reached the parent; no follow-up", alert.id)
            return
        message = await db.get(Message, alert.message_id)
        if message is None:
            raise PermanentError("alert's message no longer exists")
        chat = await db.get(Chat, message.chat_id)
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        recipient = await get_setting(db, "alerts.recipient")
        sender = await db.get(Instance, sender_id) if sender_id else None
        if not recipient or sender is None or not sender.openwa_api_key_enc:
            raise PermanentError("alert delivery not configured")
        timezone = str(await get_setting(db, "alerts.timezone"))
        text = format_change_notice(
            kind, build_facts(alert, message, chat), timezone, deps.public_base_url, deps.key_bytes
        )
        client = OpenWAClient(
            sender.openwa_base_url, decrypt(deps.key_bytes, sender.openwa_api_key_enc)
        )
        try:
            await client.send_text(sender.openwa_instance_id, recipient_chat_id(recipient), text)
        except OpenWAError as exc:
            if exc.status is None or exc.status >= 500 or exc.status == 429:
                raise TransientError(f"follow-up delivery failed: {exc.message}") from exc
            raise PermanentError(f"follow-up delivery rejected: {exc.message}") from exc
        finally:
            await client.aclose()
        logger.info("alert {} follow-up ({}) delivered", alert.id, kind)
