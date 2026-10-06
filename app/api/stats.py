"""/api/stats and /api/chats: dashboard numbers and the known-chats list."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.service import delivery_configured
from app.db.models import Alert, Chat, ChatInstance, Instance, Job, Message
from app.deps import get_db
from app.security.auth import current_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


class Stats(BaseModel):
    messages_today: int
    messages_7d: int
    alerts_by_status: dict[str, int]
    alerts_by_delivery: dict[str, int]
    review_queue: int
    jobs_by_status: dict[str, int]
    queue_depth: int  # queued + running
    failed_jobs: int  # failed + dead
    delivery_configured: bool
    instances: int
    silent_instances: int  # enabled but never received a webhook


async def _count(db: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    return int((await db.execute(stmt)).scalar_one())


@router.get("/stats")
async def stats(db: DB) -> Stats:
    now = datetime.now(UTC).replace(tzinfo=None)  # stored as naive UTC
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_alert = dict(
        (await db.execute(select(Alert.status, func.count()).group_by(Alert.status))).all()
    )
    by_delivery = dict(
        (
            await db.execute(
                select(Alert.delivery_status, func.count()).group_by(Alert.delivery_status)
            )
        ).all()
    )
    jobs = {
        str(k): int(v)
        for k, v in (await db.execute(select(Job.status, func.count()).group_by(Job.status))).all()
    }
    return Stats(
        messages_today=await _count(
            db, select(func.count()).select_from(Message).where(Message.sent_at >= day)
        ),
        messages_7d=await _count(
            db,
            select(func.count())
            .select_from(Message)
            .where(Message.sent_at >= now - timedelta(days=7)),
        ),
        alerts_by_status={str(k): int(v) for k, v in by_alert.items()},
        alerts_by_delivery={str(k): int(v) for k, v in by_delivery.items()},
        review_queue=await _count(
            db, select(func.count()).select_from(Message).where(Message.verdict == "review")
        ),
        jobs_by_status=jobs,
        queue_depth=jobs.get("queued", 0) + jobs.get("running", 0),
        failed_jobs=jobs.get("failed", 0) + jobs.get("dead", 0),
        delivery_configured=await delivery_configured(db),
        instances=await _count(db, select(func.count()).select_from(Instance)),
        silent_instances=await _count(
            db,
            select(func.count())
            .select_from(Instance)
            .where(Instance.enabled.is_(True), Instance.last_webhook_at.is_(None)),
        ),
    )


class ChatKid(BaseModel):
    id: int
    kid_name: str


class ChatOut(BaseModel):
    id: int
    wa_chat_id: str
    name: str | None
    is_group: bool
    kids: list[ChatKid]
    message_count: int
    alert_count: int
    last_message_at: datetime | None


@router.get("/chats")
async def list_chats(db: DB) -> list[ChatOut]:
    msg = (
        select(Message.chat_id, func.count().label("n"), func.max(Message.sent_at).label("last"))
        .group_by(Message.chat_id)
        .subquery()
    )
    alerts = (
        select(Message.chat_id, func.count().label("n"))
        .join(Alert, Alert.message_id == Message.id)
        .group_by(Message.chat_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Chat, msg.c.n, msg.c.last, alerts.c.n)
            .outerjoin(msg, msg.c.chat_id == Chat.id)
            .outerjoin(alerts, alerts.c.chat_id == Chat.id)
            .order_by(
                msg.c.last.is_(None), msg.c.last.desc(), Chat.id.desc()
            )  # NULLs last everywhere
        )
    ).all()
    kids: dict[int, list[ChatKid]] = {}
    for chat_id, iid, name in await db.execute(
        select(ChatInstance.chat_id, Instance.id, Instance.kid_name)
        .join(Instance, Instance.id == ChatInstance.instance_id)
        .order_by(Instance.id)
    ):
        kids.setdefault(chat_id, []).append(ChatKid(id=iid, kid_name=name))
    return [
        ChatOut(
            id=c.id,
            wa_chat_id=c.wa_chat_id,
            name=c.name,
            is_group=c.is_group,
            kids=kids.get(c.id, []),
            message_count=int(n or 0),
            alert_count=int(a or 0),
            last_message_at=last,
        )
        for c, n, last, a in rows
    ]


class DayActivity(BaseModel):
    date: date
    safe: int
    review: int
    harmful: int
    other: int  # pending, skipped or failed: no verdict
    alerts: int


class Timeline(BaseModel):
    timezone: str
    days: list[DayActivity]


@router.get("/stats/timeline")
async def timeline(db: DB, days: Annotated[int, Query(ge=1, le=90)] = 14) -> Timeline:
    """Messages (by verdict) and alerts per day for the last `days` days, zero-filled.

    Days are the parent's days: bucketed in the `alerts.timezone` setting, not in UTC. The
    database stores naive UTC, so the bucketing happens here rather than in SQL (daylight
    saving changes make a fixed SQL offset wrong).
    """
    tz = ZoneInfo(str(await get_setting(db, "alerts.timezone")))
    today = datetime.now(tz).date()
    first = today - timedelta(days=days - 1)
    start_utc = (
        datetime.combine(first, datetime.min.time(), tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
    )

    def local_day(naive_utc: datetime) -> date:
        return naive_utc.replace(tzinfo=UTC).astimezone(tz).date()

    buckets: dict[date, dict[str, int]] = defaultdict(
        lambda: {"safe": 0, "review": 0, "harmful": 0, "other": 0, "alerts": 0}
    )
    for sent_at, verdict in await db.execute(
        select(Message.sent_at, Message.verdict).where(Message.sent_at >= start_utc)
    ):
        key = verdict if verdict in ("safe", "review", "harmful") else "other"
        buckets[local_day(sent_at)][key] += 1
    for (created_at,) in await db.execute(
        select(Alert.created_at).where(Alert.created_at >= start_utc)
    ):
        buckets[local_day(created_at)]["alerts"] += 1
    return Timeline(
        timezone=str(tz),
        days=[
            DayActivity(date=d, **buckets[d])
            for d in (first + timedelta(days=i) for i in range(days))
        ],
    )
