"""Daily quiet windows. Durable queue deferral never consumes a sending/retry budget."""

from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job
from app.jobs.queue import ClaimedJob, DeferredError, ensure_owned
from app.settings_store import get_setting


def _boundary(wall: datetime, zone: ZoneInfo, *, latest: bool) -> datetime:
    # Repeated end time: wait until its second occurrence. A skipped end time moves
    # forward to the first real local minute, rather than sending before the window ends.
    for _ in range(26 * 60):
        valid = []
        for fold in (0, 1):
            candidate = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if candidate.astimezone(zone).replace(tzinfo=None) == wall:
                valid.append(candidate)
        if valid:
            return max(valid) if latest else min(valid)
        wall += timedelta(minutes=1)
    raise ValueError("Unable to resolve the quiet-hours end time")


def quiet_until(config: dict[str, Any], timezone: str, now: datetime) -> datetime | None:
    if not config["enabled"]:
        return None
    if now.tzinfo is None:
        raise ValueError("Quiet hours require an aware timestamp")
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    start, end = time.fromisoformat(config["start"]), time.fromisoformat(config["end"])
    for day in (local.date() - timedelta(days=1), local.date()):
        begins = _boundary(datetime.combine(day, start), zone, latest=False)
        ends = _boundary(
            datetime.combine(day + timedelta(days=int(start > end)), end), zone, latest=True
        )
        if begins <= now.astimezone(UTC) < ends:
            return ends
    return None


async def defer_if_quiet(
    db: AsyncSession, job: ClaimedJob, scope: Literal["parent", "system"]
) -> None:
    now = datetime.now(UTC)
    due = quiet_until(
        await get_setting(db, f"alerts.{scope}_quiet_hours"),
        str(await get_setting(db, "alerts.timezone")),
        now,
    )
    if due is None:
        return
    job.payload["quiet_hours_deferred"] = True
    job.payload["quiet_hours_resume_at"] = due.isoformat()
    stored = await db.get(Job, job.id)
    if stored is not None:
        await ensure_owned(db, job)
        stored.payload = dict(job.payload)
        await db.commit()
    raise DeferredError(
        "Waiting for quiet hours",
        max(1, (due - now).total_seconds()),
        reason="Waiting for quiet hours",
    )
