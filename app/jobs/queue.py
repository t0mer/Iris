"""DB-backed job queue: enqueue, claim, ack, retry with backoff, dead-letter.

SQLite has a single writer, so claiming is optimistic: pick the next eligible job, then
UPDATE ... WHERE id=:id AND status='queued' and treat rowcount==1 as ownership.
All timestamps are naive-UTC in the database (SQLite drops tzinfo).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Alert, Job, Message
from app.metrics import ALERTS

BACKOFF_SECONDS = (5, 30, 120, 600, 1800)
STALE_LOCK = timedelta(minutes=10)


class TransientError(Exception):
    """Network / 429 / 5xx: retry with backoff. `retry_after` (seconds) overrides the schedule."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(Exception):
    """Bad input or configuration: fail immediately, no retries."""


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


def _now() -> datetime:
    return datetime.now(UTC)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


async def enqueue(
    db: AsyncSession, type_: str, payload: dict[str, Any], *, max_attempts: int = 5
) -> int:
    job = Job(type=type_, payload=payload, max_attempts=max_attempts)
    db.add(job)
    await db.commit()
    return job.id


async def claim(factory: async_sessionmaker[AsyncSession]) -> ClaimedJob | None:
    async with factory() as db:
        now = _naive(_now())
        candidate = (
            await db.execute(
                select(Job.id)
                .where(Job.status == "queued", Job.run_after <= now)
                .order_by(Job.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if candidate is None:
            return None
        res = await db.execute(
            update(Job)
            .where(Job.id == candidate, Job.status == "queued")
            .values(status="running", locked_at=now, attempts=Job.attempts + 1)
        )
        await db.commit()
        if res.rowcount != 1:  # type: ignore[attr-defined]
            return None  # another worker took it
        job = await db.get(Job, candidate)
        assert job is not None
        return ClaimedJob(job.id, job.type, job.payload, job.attempts, job.max_attempts)


async def ack(factory: async_sessionmaker[AsyncSession], job_id: int) -> None:
    async with factory() as db:
        await db.execute(update(Job).where(Job.id == job_id).values(status="done", locked_at=None))
        await db.commit()


def backoff_for(attempt: int, retry_after: float | None = None) -> timedelta:
    base = BACKOFF_SECONDS[min(max(attempt, 1), len(BACKOFF_SECONDS)) - 1]
    return timedelta(seconds=max(base, min(retry_after or 0, 3600)))


async def fail(
    factory: async_sessionmaker[AsyncSession],
    job: ClaimedJob,
    error: str,
    *,
    transient: bool,
    retry_after: float | None = None,
) -> str:
    """Record a failure. Returns the new job status: queued (retry), dead or failed."""
    async with factory() as db:
        if transient and job.attempts < job.max_attempts:
            run_after = _naive(_now() + backoff_for(job.attempts, retry_after))
            await db.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(
                    status="queued", locked_at=None, last_error=error[:500], run_after=run_after
                )
            )
            await db.commit()
            return "queued"
        status = "dead" if transient else "failed"
        await db.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(status=status, locked_at=None, last_error=error[:500])
        )
        message_id = job.payload.get("message_id")
        if job.type == "process_message" and isinstance(message_id, int):
            await db.execute(
                update(Message).where(Message.id == message_id).values(status="failed")
            )
        alert_id = job.payload.get("alert_id")
        # Only a delivery that ran out of attempts fails its alert; a lost follow-up must not
        # turn an alert the parent already received into a "failed" one.
        if job.type == "deliver_alert" and isinstance(alert_id, int):
            alert = await db.get(Alert, alert_id)
            if alert is not None:
                ALERTS.labels(
                    alert.categories[0] if alert.categories else "unknown", "failed"
                ).inc()
            await db.execute(
                update(Alert)
                .where(Alert.id == alert_id)
                .values(delivery_status="failed", delivery_error=error[:500])
            )
        await db.commit()
        return status


async def recover_stale(factory: async_sessionmaker[AsyncSession]) -> int:
    """Jobs left 'running' by a crashed process go back to the queue, or are dead-lettered once
    they have used all their attempts (so a job that kills the process cannot loop forever)."""
    async with factory() as db:
        cutoff = _naive(_now() - STALE_LOCK)
        stale = (
            (await db.execute(select(Job).where(Job.status == "running", Job.locked_at < cutoff)))
            .scalars()
            .all()
        )
        for job in stale:
            if job.attempts >= job.max_attempts:
                job.status, job.locked_at, job.last_error = "dead", None, "worker crashed or hung"
                mid = job.payload.get("message_id")
                if isinstance(mid, int):
                    await db.execute(
                        update(Message).where(Message.id == mid).values(status="failed")
                    )
            else:
                job.status, job.locked_at = "queued", None
        await db.commit()
        return len(stale)


async def has_active_job(db: AsyncSession, message_id: int) -> bool:
    """True if a queued or running job already targets this message."""
    n = (
        await db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.status.in_(["queued", "running"]),
                func.json_extract(Job.payload, "$.message_id") == message_id,
            )
        )
    ).scalar_one()
    return int(n) > 0


async def retry_job(db: AsyncSession, job_id: int) -> bool:
    """Manual retry of a failed/dead job (Jobs page)."""
    job = await db.get(Job, job_id)
    if job is None or job.status not in ("failed", "dead"):
        return False
    mid = job.payload.get("message_id")
    if isinstance(mid, int) and await has_active_job(db, mid):
        return False  # another job for this message is already waiting or running
    job.status, job.attempts, job.last_error, job.run_after = "queued", 0, None, _naive(_now())
    message_id = job.payload.get("message_id")
    if isinstance(message_id, int):
        await db.execute(update(Message).where(Message.id == message_id).values(status="pending"))
    await db.commit()
    return True
