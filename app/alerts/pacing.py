"""Traffic budgets, not a promise against provider account restrictions."""

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SendingBudget
from app.jobs.queue import DeferredError
from app.settings_store import get_setting


def recipient_key(sender: str, recipient: str) -> str:
    return sender + ":" + hashlib.sha256(recipient.encode()).hexdigest()


async def reserve(
    db: AsyncSession,
    sender: str,
    recipient: str,
    *,
    now: datetime | None = None,
    authentication: bool = False,
) -> None:
    """Atomically reserve sender and recipient capacity before making a provider call.

    A failed/uncertain send still consumes capacity. Never hold workers asleep while waiting.
    Authentication uses its own budget and rejects promptly instead of storing expiring codes.
    """
    now = now or datetime.now(UTC)
    if authentication:
        limits = ((sender, 5, 60, 250), (recipient_key(sender, recipient), 60, 5, 20))
    else:
        spacing = int(await get_setting(db, "alerts.send_interval_seconds"))
        hourly = int(await get_setting(db, "alerts.send_hourly_limit"))
        daily = int(await get_setting(db, "alerts.send_daily_limit"))
        limits = ((sender, spacing, hourly, daily), (recipient_key(sender, recipient), 60, 20, 100))
    try:
        rows = []
        for key, spacing, hourly, daily in limits:
            row = await db.get(SendingBudget, key)
            if row is None:
                row = SendingBudget(
                    key=key,
                    generation=0,
                    next_allowed=now,
                    hour_start=now,
                    hour_count=0,
                    day_start=now,
                    day_count=0,
                )
                db.add(row)
                await db.flush()
            hour_start = row.hour_start if now < row.hour_start + timedelta(hours=1) else now
            day_start = row.day_start if now < row.day_start + timedelta(days=1) else now
            hour_count = row.hour_count if hour_start != now else 0
            day_count = row.day_count if day_start != now else 0
            due = max(now, row.next_allowed)
            if hour_count >= hourly:
                due = max(due, hour_start + timedelta(hours=1))
            if day_count >= daily:
                due = max(due, day_start + timedelta(days=1))
            rows.append((row, spacing, hour_start, hour_count, day_start, day_count, due))
        due = max(row[-1] for row in rows)
        if due > now:
            await db.rollback()
            raise DeferredError(
                "Sending budget reached; queued for later", (due - now).total_seconds()
            )
        for row, spacing, hour_start, hour_count, day_start, day_count, _ in rows:
            result = await db.execute(
                update(SendingBudget)
                .where(SendingBudget.key == row.key, SendingBudget.generation == row.generation)
                .values(
                    generation=row.generation + 1,
                    next_allowed=now + timedelta(seconds=spacing),
                    hour_start=hour_start,
                    hour_count=hour_count + 1,
                    day_start=day_start,
                    day_count=day_count + 1,
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                await db.rollback()
                raise DeferredError("Sending budget changed; queued for later", 1)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DeferredError("Sending budget is being reserved; queued for later", 1) from None


async def pause_sender(db: AsyncSession, sender: str, seconds: int) -> None:
    """Provider throttling stops all queued messages for this sender, not just one job."""
    until = datetime.now(UTC) + timedelta(seconds=seconds)
    await db.execute(
        update(SendingBudget)
        .where(SendingBudget.key == sender)
        .values(
            next_allowed=case(
                (SendingBudget.next_allowed < until, until), else_=SendingBudget.next_allowed
            ),
            generation=SendingBudget.generation + 1,
        )
    )
    await db.commit()
