"""Alert creation (spec 9.1) and the sexual-content redaction rule (spec 8.5)."""

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.format import make_quote
from app.classify.pipeline import PipelineOutcome
from app.classify.thresholds import effective_thresholds
from app.config import get_settings
from app.db.models import (
    Alert,
    Chat,
    Classification,
    Instance,
    Job,
    Message,
    MessageReceipt,
    MessageRevision,
    ReviewDataIssue,
)
from app.jobs.queue import enqueue, retry_job
from app.media.records import mark_purge
from app.metrics import ALERTS
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.settings_store import get_setting

REDACTED = "[redacted]"
MEDIA_TYPES = ("image", "sticker", "video")
DELIVERY_JOB = "deliver_alert"
DELIVERY_ATTEMPTS = 3
_ALERT_LOCK = asyncio.Lock()
_REQUEUE_LOCK = asyncio.Lock()


def should_redact(message_type: str, categories: list[str]) -> bool:
    """Sexual content involving minors, or sexual imagery: never stored, never forwarded."""
    return "sexual/minors" in categories or (message_type in MEDIA_TYPES and "sexual" in categories)


def needs_redaction(message_type: str, high: list[str], low: list[str]) -> bool:
    """Decide at classification time, before anything is shown or alerted.

    `sexual/minors` at or above its high threshold is withheld. In the uncertain band (above low,
    below high) the words of a TEXT or voice message are kept so the owner can read them in the
    review queue and decide (they are withheld the moment it is confirmed harmful); anything with
    a picture (image, sticker, video) is withheld at any band. Sexual imagery is withheld at the
    high threshold, as in the spec.
    """
    if "sexual/minors" in high:
        return True
    if "sexual/minors" in low and message_type in MEDIA_TYPES:
        return True
    return should_redact(message_type, high)


def redact_for_alert(
    message_type: str,
    scores: dict[str, float],
    thresholds: dict[str, tuple[float, float]],
    confirmed: bool = False,
) -> bool:
    """The same decision when an alert is created (the scores are what triggered it).

    `confirmed` is true when the owner has just marked the message harmful: an item kept for
    review is then withheld.
    """
    minors = scores.get("sexual/minors")
    if minors is not None and (
        confirmed
        or message_type in MEDIA_TYPES
        or minors >= thresholds.get("sexual/minors", (0.05, 0.30))[1]
    ):
        return True
    return message_type in MEDIA_TYPES and "sexual" in scores


def redact_message(message: Message) -> None:
    """Withhold the content: row keeps metadata only; FTS blanks itself via the update trigger."""
    message.text = REDACTED
    message.transcript = REDACTED
    message.media = None  # no way back to the attachment (reprocess is blocked anyway)
    message.redacted = True


async def wipe_revisions(db: AsyncSession, message_id: int) -> None:
    """Withheld content must not survive in the edit history either."""
    await db.execute(delete(MessageRevision).where(MessageRevision.message_id == message_id))


async def _kid_names(db: AsyncSession, message_id: int) -> list[str]:
    rows = await db.execute(
        select(Instance.kid_name)
        .join(MessageReceipt, MessageReceipt.instance_id == Instance.id)
        .where(MessageReceipt.message_id == message_id)
        .order_by(Instance.id)
    )
    return list(rows.scalars())


async def delivery_configured(db: AsyncSession) -> bool:
    from app.alerts.channels import configured

    return await configured(db)


async def flagged_union(db: AsyncSession, message_id: int) -> set[str]:
    """Every category any stage flagged (a later look may clear what an earlier one saw)."""
    rows = await db.execute(
        select(Classification.flagged_categories).where(Classification.message_id == message_id)
    )
    return {c for (cats,) in rows for c in cats}


def active_source(message_id: Any) -> ColumnElement[bool]:
    """A shared message can notify only while at least one receipt phone is monitored."""
    return (
        select(MessageReceipt.message_id)
        .join(Instance, Instance.id == MessageReceipt.instance_id)
        .where(MessageReceipt.message_id == message_id, Instance.enabled.is_(True))
        .exists()
    )


async def create_alert(
    db: AsyncSession, message: Message, scores: dict[str, float], confirmed: bool = False
) -> Alert:
    async with _ALERT_LOCK:
        return await _create_alert(db, message, scores, confirmed)


async def _create_alert(
    db: AsyncSession, message: Message, scores: dict[str, float], confirmed: bool = False
) -> Alert:
    """Create the alert for a message (one per message) and queue its delivery.

    `scores` maps the triggering categories to their scores. Redaction and the alert row are
    committed together, so withheld content can never be quoted by a half-finished alert. The
    decision looks at every stage's flags, and runs even when the alert already exists, so
    confirming an item as harmful always withholds it.
    """
    existing = (
        await db.execute(select(Alert).where(Alert.message_id == message.id))
    ).scalar_one_or_none()
    thresholds = effective_thresholds(await get_setting(db, "classification.thresholds"))
    flags = await flagged_union(db, message.id)
    seen = {**{c: 0.0 for c in flags}, **scores}  # what any stage flagged, with the best scores
    redact = message.redacted or redact_for_alert(message.type, seen, thresholds, confirmed)
    # Uncertain text about minors is kept for the owner to read in the portal, but it is never
    # copied into an alert (and so never sent over WhatsApp).
    keep_out_of_alert = redact or "sexual/minors" in seen
    if existing is not None:
        if redact and not message.redacted:
            redact_message(message)
            await wipe_revisions(db, message.id)
            await mark_purge(db, message.id)
            existing.quote = None
            await db.commit()
            logger.warning("message {} redacted on confirmation; content withheld", message.id)
        if confirmed and existing.delivery_status in ("failed", "suppressed", "paused"):
            await queue_existing_alert(db, existing, message, force=True)
        return existing

    ordered = sorted((scores or {"manual review": 0.0}).items(), key=lambda kv: kv[1], reverse=True)
    categories = [c for c, _ in ordered]
    chat = await db.get(Chat, message.chat_id)
    if redact:
        redact_message(message)
        await wipe_revisions(db, message.id)
        await mark_purge(db, message.id)
        logger.warning("message {} redacted ({}); content withheld", message.id, categories)
    quote = (
        None if keep_out_of_alert else make_quote(message.type, message.text, message.transcript)
    )

    alert = Alert(
        message_id=message.id,
        categories=categories,
        max_score=ordered[0][1] if ordered else 0.0,
        kid_names=await _kid_names(db, message.id),
        chat_name=chat.name if chat else None,
        sender_name=message.sender_name,
        quote=quote,
        status="new",
        delivery_status="pending",
    )
    db.add(alert)
    await db.flush()
    if not await db.scalar(select(active_source(message.id))):
        alert.delivery_status = "paused"
        alert.delivery_error = "Monitoring is paused or the source phone was removed"
    elif await delivery_configured(db):
        await enqueue(db, DELIVERY_JOB, {"alert_id": alert.id}, max_attempts=DELIVERY_ATTEMPTS)
    else:
        from app.alerts.readiness import delivery_readiness

        alert.delivery_status = "failed"
        alert.delivery_error = (
            "alert delivery not configured: " + (await delivery_readiness(db)).error
        )
        ALERTS.labels(categories[0], "failed").inc()
    await db.commit()
    return alert


def outcome_scores(outcome: PipelineOutcome) -> dict[str, float]:
    """Triggering categories (and scores) of the stage that decided the verdict."""
    final = outcome.results[-1].scores if outcome.results else {}
    return {c: float(final[c]) for c in outcome.categories if c in final}


async def scores_from_classifications(db: AsyncSession, message: Message) -> dict[str, float]:
    """For a manual 'harmful' from the review queue: the categories at or above their low
    threshold in the latest classification (the message was inconclusive, so none reached high)."""
    last = (
        await db.execute(
            select(Classification)
            .where(Classification.message_id == message.id)
            .order_by(Classification.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None:
        return {}
    scores: dict[str, Any] = last.scores
    return {c: float(scores[c]) for c in last.flagged_categories if c in scores}


async def alert_on_harmful(db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    await create_alert(db, message, outcome_scores(outcome))


async def alert_on_review(db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    """Review items alert only when the parent opted in (alerts.alert_on_review)."""
    if not await get_setting(db, "alerts.alert_on_review"):
        return
    last = outcome.results[-1] if outcome.results else None
    if last is None:
        if get_settings().local_safety_mode:
            await create_alert(db, message, {})
        return
    scores = {c: float(last.scores[c]) for c in last.flagged_categories if c in last.scores}
    await create_alert(db, message, scores)


async def queue_existing_alert(
    db: AsyncSession, alert: Alert, message: Message, force: bool = False
) -> None:
    async with _REQUEUE_LOCK:
        await _queue_existing_alert(db, alert, message, force)


async def _queue_existing_alert(
    db: AsyncSession, alert: Alert, message: Message, force: bool = False
) -> None:
    if not await delivery_configured(db) or not await db.scalar(select(active_source(message.id))):
        return
    jobs = list(
        (
            await db.scalars(
                select(Job)
                .where(Job.type == DELIVERY_JOB, Job.payload["alert_id"].as_integer() == alert.id)
                .order_by(Job.id.desc())
            )
        ).all()
    )
    if any(job.status in ("queued", "running") for job in jobs):
        return
    alert.delivery_status, alert.delivery_error = "pending", None
    if jobs:
        job = jobs[0]
        # Preserve completed recipient checkpoints when recovering a failed delivery.
        job.payload = {**job.payload, "force": force}
        if job.status in ("failed", "dead"):
            await retry_job(db, job.id, manual=force)
        else:
            await enqueue(
                db,
                DELIVERY_JOB,
                {"alert_id": alert.id, "force": force},
                max_attempts=DELIVERY_ATTEMPTS,
            )
    else:
        await enqueue(
            db, DELIVERY_JOB, {"alert_id": alert.id, "force": force}, max_attempts=DELIVERY_ATTEMPTS
        )
    await db.commit()


async def notify_pending_reviews(db: AsyncSession) -> None:
    """Catch up harmful/review notifications and resume held deliveries when configured."""
    if not await delivery_configured(db):
        return
    if await get_setting(db, "alerts.channel") == "openwa" and not await get_setting(
        db, "alerts.recipient_channels"
    ):
        sender = await db.get(Instance, await get_setting(db, "alerts.sender_instance_id"))
        if sender is None or not sender.openwa_api_key_enc:
            return
        client = OpenWAClient(
            sender.openwa_base_url, decrypt(get_settings().key_bytes, sender.openwa_api_key_enc)
        )
        try:
            if not await client.session_ready(sender.openwa_instance_id):
                return  # preserve the queue while WhatsApp reconnects
        except OpenWAError:
            return
        finally:
            await client.aclose()
    review_enabled = bool(await get_setting(db, "alerts.alert_on_review"))
    since_value = await get_setting(db, "alerts.review_notify_since")
    since = (
        datetime.fromisoformat(since_value).replace(tzinfo=None) if since_value else datetime.min
    )

    held = (
        await db.execute(
            select(Alert, Message)
            .join(Message, Message.id == Alert.message_id)
            .where(
                Alert.delivery_status == "paused",
                (Message.verdict != "review") | (Message.received_at >= since),
                (Message.verdict != "review") | ~Message.id.in_(select(ReviewDataIssue.message_id)),
                active_source(Message.id),
                Message.verdict.in_(("harmful", "review") if review_enabled else ("harmful",)),
            )
            .order_by(Alert.id)
            .limit(20)
        )
    ).all()
    for alert, message in held:
        await queue_existing_alert(db, alert, message)
    missing = list(
        (
            await db.scalars(
                select(Message)
                .where(
                    Message.verdict == "harmful",
                    active_source(Message.id),
                    Message.id.not_in(select(Alert.message_id)),
                )
                .order_by(Message.id)
                .limit(20)
            )
        ).all()
    )
    for message in missing:
        await create_alert(db, message, await scores_from_classifications(db, message))
    if not review_enabled:
        return
    # Retry each failed review delivery once after the sender is ready. Invalid recipients
    # must stay visibly failed rather than causing an unbounded resend loop.
    failures = (
        await db.execute(
            select(Alert, Job)
            .join(Message, Message.id == Alert.message_id)
            .outerjoin(
                Job, (Job.type == DELIVERY_JOB) & (Job.payload["alert_id"].as_integer() == Alert.id)
            )
            .where(
                (Message.verdict == "review") & ~Message.id.in_(select(ReviewDataIssue.message_id)),
                active_source(Message.id),
                Alert.delivery_status == "failed",
                Message.received_at >= since,
                Alert.notified_at.is_(None),
            )
            .order_by(Job.id.desc())
        )
    ).all()
    seen: set[int] = set()
    recovered = 0
    for alert, job in failures:
        if alert.id in seen:
            continue
        seen.add(alert.id)
        if job is not None and (
            job.status not in ("failed", "dead")
            or job.payload.get("review_recovery_attempted")
            or job.payload.get("delivery_uncertain")
        ):
            continue
        alert.delivery_status, alert.delivery_error = "pending", None
        if job is None:
            await enqueue(
                db,
                DELIVERY_JOB,
                {"alert_id": alert.id, "review_recovery_attempted": True},
                max_attempts=DELIVERY_ATTEMPTS,
            )
        else:
            job.payload = {**job.payload, "review_recovery_attempted": True}
            await retry_job(db, job.id)
        recovered += 1
        if recovered >= 20:
            break
    rows = list(
        (
            await db.scalars(
                select(Message)
                .where(
                    (Message.verdict == "review")
                    & ~Message.id.in_(select(ReviewDataIssue.message_id)),
                    Message.received_at >= since,
                    active_source(Message.id),
                    Message.id.not_in(select(Alert.message_id)),
                )
                .order_by(Message.id)
                .limit(20)
            )
        ).all()
    )
    for message in rows:
        await create_alert(db, message, await scores_from_classifications(db, message))
