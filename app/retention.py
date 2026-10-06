"""Hourly retention (spec 12): old messages, alerts, finished jobs and empty chats are deleted."""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Alert, Chat, Job, Message
from app.settings_store import get_setting

JOB_RETENTION = timedelta(days=7)  # finished jobs
FAILED_JOB_RETENTION = timedelta(days=30)  # failed/dead jobs keep their error visible longer
INTERVAL_SECONDS = 3600


async def run_retention(
    factory: async_sessionmaker[AsyncSession], now: datetime | None = None
) -> dict[str, int]:
    """One pass. Deleting a message cascades to its classifications, receipts and search row
    (FK cascade + FTS trigger).

    A message is kept while ANY alert still references it: the alert row cascades with its
    message, so deleting the message early would cut the alert's own retention short. Alerts
    are removed first, by `retention.alert_days`, which then frees their messages."""
    now = (now or datetime.now(UTC)).replace(tzinfo=None)  # the database stores naive UTC
    async with factory() as db:
        message_days = int(await get_setting(db, "retention.message_days"))
        alert_days = int(await get_setting(db, "retention.alert_days"))

        alerts = await db.execute(
            delete(Alert).where(Alert.created_at < now - timedelta(days=alert_days))
        )
        messages = await db.execute(
            delete(Message).where(
                Message.sent_at < now - timedelta(days=message_days),
                Message.id.not_in(select(Alert.message_id)),
            )
        )
        jobs = await db.execute(
            delete(Job).where(
                ((Job.status == "done") & (Job.created_at < now - JOB_RETENTION))
                | (
                    Job.status.in_(["failed", "dead"])
                    & (Job.created_at < now - FAILED_JOB_RETENTION)
                )
            )
        )
        chats = await db.execute(delete(Chat).where(Chat.id.not_in(select(Message.chat_id))))
        await db.commit()
    result = {
        "alerts": int(alerts.rowcount),  # type: ignore[attr-defined]
        "messages": int(messages.rowcount),  # type: ignore[attr-defined]
        "jobs": int(jobs.rowcount),  # type: ignore[attr-defined]
        "chats": int(chats.rowcount),  # type: ignore[attr-defined]
    }
    if any(result.values()):
        logger.info("retention removed {}", result)
    return result


async def retention_loop(factory: async_sessionmaker[AsyncSession]) -> None:
    while True:
        try:
            await run_retention(factory)
        except Exception:
            logger.exception("retention pass failed")
        await asyncio.sleep(INTERVAL_SECONDS)
