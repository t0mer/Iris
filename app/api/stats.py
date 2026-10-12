"""/api/stats and /api/chats: dashboard numbers and the known-chats list."""

import asyncio
import json
import os
import shutil
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, literal, select, true
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from app.alerts.media_status import missing_media_copy
from app.alerts.readiness import delivery_readiness
from app.config import get_settings
from app.db.models import (
    Alert,
    AlertView,
    Chat,
    ChatInstance,
    Instance,
    Job,
    MediaWarningDismissal,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ScheduleRun,
    StoredMedia,
    User,
)
from app.deps import get_db
from app.resources import container_resources
from app.review_queue import ai_pending
from app.security.auth import admin_user, current_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


class Stats(BaseModel):
    messages_today: int
    messages_7d: int
    alerts_by_status: dict[str, int]
    alerts_by_delivery: dict[str, int]
    review_queue: int
    iris_review_queue: int = 0
    jobs_by_status: dict[str, int]
    queue_depth: int  # queued + running
    failed_jobs: int  # failed + dead
    delivery_configured: bool
    instances: int
    children: int = 0
    parent_recipients: int = 0
    alert_phones: int = 0
    alert_sender_configured: bool = False
    silent_instances: int  # enabled but never received a webhook
    media_policy: str  # off | harmful | harmful_review | all
    media_files: int  # kept media that can be shown
    media_bytes: int
    alert_media_not_saved: int = 0
    alert_media_warning_count: int = 0
    alert_media_warning_latest_id: int = 0
    alert_channel: str = "openwa"
    sender_is_recipient: bool = False
    unavailable_instances: int = 0
    monitoring_window_minutes: int = 0
    alert_delivery_issues: list[str] = []
    eligible_alert_recipients: int = 0
    invalid_alert_recipients: int = 0
    monitoring_issues: list[dict[str, object]] = []
    schedule_failures: list[dict[str, str]] = []
    provider_health: list[dict[str, object]] = []


async def _count(db: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    return int((await db.execute(stmt)).scalar_one())


class DismissMediaWarning(BaseModel):
    through_alert_id: int = Field(ge=0)


@router.post("/stats/media-warning/dismiss")
async def dismiss_media_warning(
    body: DismissMediaWarning, db: DB, user: Annotated[User, Depends(current_user)]
) -> dict[str, bool]:
    affected = (
        select(Alert.id, literal(user.id))
        .join(Message, Message.id == Alert.message_id)
        .where(missing_media_copy(), Alert.id <= body.through_alert_id)
    )
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        mysql_statement = mysql_insert(MediaWarningDismissal).from_select(
            ["alert_id", "user_id"], affected
        )
        statement: Insert = mysql_statement.on_duplicate_key_update(
            user_id=mysql_statement.inserted.user_id
        )
    else:
        insert = postgres_insert if dialect == "postgresql" else sqlite_insert
        statement = (
            insert(MediaWarningDismissal)
            .from_select(["alert_id", "user_id"], affected)
            .on_conflict_do_nothing()
        )
    await db.execute(statement)
    await db.commit()
    from app.events import bus

    bus.publish("stats")
    return {"dismissed": True}


@router.get("/stats")
async def stats(db: DB, user: Annotated[User | None, Depends(current_user)] = None) -> Stats:
    warning_query = (
        select(func.count(), func.coalesce(func.max(Alert.id), 0))
        .select_from(Alert)
        .join(Message, Message.id == Alert.message_id)
        .where(missing_media_copy())
    )
    if user is not None:
        warning_query = warning_query.where(
            Alert.id.not_in(
                select(MediaWarningDismissal.alert_id).where(
                    MediaWarningDismissal.user_id == user.id
                )
            )
        )
    warning_count, warning_latest_id = (await db.execute(warning_query)).one()
    now = datetime.now(UTC).replace(tzinfo=None)  # stored as naive UTC
    timezone = ZoneInfo(str(await get_setting(db, "alerts.timezone")))
    local_today = datetime.now(timezone).date()
    day = (
        datetime.combine(local_today, datetime.min.time(), tzinfo=timezone)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )
    by_alert = dict(
        (await db.execute(select(Alert.status, func.count()).group_by(Alert.status))).all()
    )
    if user is not None:
        personal_status = func.coalesce(AlertView.status, "new")
        by_alert = dict(
            (
                await db.execute(
                    select(personal_status, func.count())
                    .select_from(Alert)
                    .outerjoin(
                        AlertView, (AlertView.alert_id == Alert.id) & (AlertView.user_id == user.id)
                    )
                    .group_by(personal_status)
                )
            ).all()
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
    cfg = get_settings()
    from app.monitoring import states

    sender_id = await get_setting(db, "alerts.sender_instance_id")
    sender = await db.get(Instance, sender_id) if sender_id else None
    from app.alerts.recipients import recipients

    try:
        targets = recipients(await get_setting(db, "alerts.recipient"))
    except ValueError:
        targets = []
    phones = list((await db.scalars(select(Instance))).all())
    roles = await get_setting(db, "phones.roles")
    parent_ids = {phone.id for phone in phones if roles.get(str(phone.id)) == "parent"}
    sender_ids = parent_ids | ({sender.id} if sender else set())
    sender_is_recipient = bool(
        sender and sender.phone_number and (sender.phone_number.lstrip("+") + "@c.us" in targets)
    )
    readiness = await delivery_readiness(db)
    from app.schedules import health_issues

    recent_runs = list(
        await db.scalars(
            select(ScheduleRun).where(
                ScheduleRun.id.in_(
                    select(func.max(ScheduleRun.id)).group_by(ScheduleRun.schedule_key)
                )
            )
        )
    )
    from app.provider_health import health_rows

    return Stats(
        provider_health=await health_rows(db) if user and user.role == "admin" else [],
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
            db,
            select(func.count())
            .select_from(Message)
            .where(
                (Message.verdict == "review")
                & ~ai_pending()
                & ~Message.id.in_(select(ReviewDataIssue.message_id))
            ),
        ),
        iris_review_queue=await _count(
            db,
            select(func.count()).select_from(Message).where(ai_pending()),
        ),
        jobs_by_status=jobs,
        queue_depth=jobs.get("queued", 0) + jobs.get("running", 0),
        failed_jobs=jobs.get("failed", 0) + jobs.get("dead", 0),
        delivery_configured=readiness.ready,
        alert_delivery_issues=readiness.issues,
        eligible_alert_recipients=len(readiness.eligible_targets),
        invalid_alert_recipients=sum(not r.eligible for r in readiness.recipients),
        monitoring_issues=await health_issues(db),
        schedule_failures=[
            {"key": r.schedule_key, "error": r.error or "Schedule failed"}
            for r in recent_runs
            if r.status == "failed"
        ],
        instances=len(phones),
        children=sum(phone.id not in parent_ids for phone in phones),
        parent_recipients=len(targets),
        alert_phones=len(sender_ids),
        alert_sender_configured=sender is not None
        or await get_setting(db, "alerts.channel") != "openwa",
        silent_instances=await _count(
            db,
            select(func.count())
            .select_from(Instance)
            .where(
                Instance.enabled.is_(True),
                Instance.last_webhook_at.is_(None),
                Instance.id.not_in(sender_ids),
            ),
        ),
        alert_channel=str(await get_setting(db, "alerts.channel")),
        alert_media_warning_count=int(warning_count),
        alert_media_warning_latest_id=int(warning_latest_id),
        alert_media_not_saved=await _count(
            db,
            select(func.count())
            .select_from(Alert)
            .join(Message, Message.id == Alert.message_id)
            .where(missing_media_copy()),
        ),
        media_policy=str(await get_setting(db, "media.policy")),
        media_files=await _count(
            db, select(func.count()).select_from(StoredMedia).where(StoredMedia.purge.is_(False))
        ),
        media_bytes=await _count(
            db,
            select(func.coalesce(func.sum(StoredMedia.size_bytes), 0)).where(
                StoredMedia.purge.is_(False)
            ),
        ),
        sender_is_recipient=sender_is_recipient,
        unavailable_instances=sum(
            not states.get(phone.id, True)
            for phone in phones
            if phone.enabled or phone.id == sender_id
        ),
        monitoring_window_minutes=cfg.monitoring_silence_minutes,
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
async def list_chats(
    db: DB,
    q: str | None = None,
    instance_id: int | None = None,
    sender: str | None = None,
    type: str | None = None,
    verdict: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> list[ChatOut]:
    from app.api.messages import message_filters

    conds, _ = await message_filters(
        db,
        q=q,
        instance_id=instance_id,
        sender=sender,
        type=type,
        verdict=verdict,
        from_=from_,
        to=to,
    )
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
            .where(Chat.id.in_(select(Message.chat_id).where(*conds)) if conds else true())
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
async def timeline(
    db: DB,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
    instance_id: Annotated[int | None, Query(ge=1)] = None,
) -> Timeline:
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
    selected = select(MessageReceipt.message_id).where(MessageReceipt.instance_id == instance_id)
    messages_query = select(Message.sent_at, Message.verdict).where(Message.sent_at >= start_utc)
    alerts_query = select(Alert.created_at).where(Alert.created_at >= start_utc)
    if instance_id is not None:
        messages_query = messages_query.where(Message.id.in_(selected))
        alerts_query = alerts_query.where(Alert.message_id.in_(selected))
    for sent_at, verdict in await db.execute(messages_query):
        key = verdict if verdict in ("safe", "review", "harmful") else "other"
        buckets[local_day(sent_at)][key] += 1
    for (created_at,) in await db.execute(alerts_query):
        buckets[local_day(created_at)]["alerts"] += 1
    return Timeline(
        timezone=str(tz),
        days=[
            DayActivity(date=d, **buckets[d])
            for d in (first + timedelta(days=i) for i in range(days))
        ],
    )


_storage_cache: dict[str, tuple[float, dict[str, int | str | None]]] = {}


def measure_directory(path: Path | None) -> dict[str, int | str | None]:
    """Measure files without following symlinks; unavailable is never reported as zero."""
    if path is None:
        return {"bytes": None, "database_bytes": None, "status": "not configured"}
    cache_key = str(path)
    cached = _storage_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    total = database = count = 0
    deadline = time.monotonic() + 5
    try:
        if not path.is_dir():
            raise OSError("missing directory")
        stack = [path]
        while stack:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    count += 1
                    if count > 100000 or time.monotonic() > deadline:
                        raise OSError("measurement limit")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat(follow_symlinks=False).st_size
                        total += size
                        if any(
                            entry.name.endswith(ext)
                            for ext in (".db", ".sqlite", ".sqlite3", "-wal", "-shm")
                        ):
                            database += size
        result: dict[str, int | str | None] = {
            "bytes": total,
            "database_bytes": database,
            "status": "measured",
        }
    except OSError:
        result = {"bytes": None, "database_bytes": None, "status": "unavailable"}
    _storage_cache[cache_key] = (time.monotonic(), result)
    return result


def provider_storage(path: Path | None, report: Path | None) -> dict[str, int | str | None]:
    if report is not None:
        try:
            value = json.loads(report.read_text())
            age = time.time() - value["measured_at"]
            if 0 <= age <= 180 and all(
                type(value.get(key)) is int and value[key] >= 0
                for key in ("bytes", "database_bytes")
            ):
                return {
                    "bytes": value["bytes"],
                    "database_bytes": value["database_bytes"],
                    "status": "measured",
                }
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return measure_directory(path)


def disk_capacity(path: Path) -> dict[str, int | str | None]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "status": "measured",
        }
    except OSError:
        return {
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "status": "unavailable",
        }


@router.get("/stats/storage", dependencies=[Depends(admin_user)])
async def storage(db: DB) -> dict[str, object]:
    cfg = get_settings()
    iris, openwa = await asyncio.gather(
        asyncio.to_thread(measure_directory, cfg.data_dir),
        asyncio.to_thread(provider_storage, cfg.openwa_data_dir, cfg.openwa_storage_report),
    )
    return {
        "iris": iris,
        "openwa": openwa,
        "disk": await asyncio.to_thread(disk_capacity, cfg.data_dir),
        "resources": await asyncio.to_thread(container_resources),
        "iris_media_bytes": await _count(
            db,
            select(func.coalesce(func.sum(StoredMedia.size_bytes), 0)).where(
                StoredMedia.purge.is_(False)
            ),
        ),
    }
