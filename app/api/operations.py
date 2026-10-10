"""Admin operations: schedule configuration/history and committed user actions."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Instance, Job, ScheduleRun, Setting
from app.deps import get_db
from app.jobs.queue import enqueue
from app.schedules import CATALOG, health_issues, prune_history, schedule_config
from app.security.auth import admin_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["operations"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/schedules")
async def schedules(db: DB) -> dict[str, Any]:
    from app.alerts.readiness import delivery_readiness
    from app.config import get_settings

    readiness = await delivery_readiness(db)
    timezone = str(await get_setting(db, "alerts.timezone"))
    assignments = await get_setting(db, "alerts.recipient_children")
    roles = await get_setting(db, "phones.roles")
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    children = {
        i.id: i.kid_name
        for i in await db.scalars(select(Instance))
        if roles.get(str(i.id)) != "parent" and i.id != sender_id
    }
    targets = readiness.public()["recipients"]
    for recipient in targets:
        recipient["children"] = [
            children[iid]
            for iid in assignments.get(recipient["target"], children)
            if iid in children
        ]
    rows = []
    for key, spec in CATALOG.items():
        await prune_history(db, key)
        runs = list(
            await db.scalars(
                select(ScheduleRun)
                .where(ScheduleRun.schedule_key == key)
                .order_by(ScheduleRun.id.desc())
            )
        )
        due = await db.get(Setting, "internal.schedule_due." + key)
        config = await schedule_config(db, key)
        next_run = None
        if config["enabled"] and config["interval"] and due and due.value.get("at"):
            next_run = datetime.fromtimestamp(due.value["at"], UTC) + timedelta(
                seconds=config["interval"]
            )
        if key == "daily_summary" and config["enabled"]:
            local = datetime.now(ZoneInfo(timezone))
            hour, minute = map(int, config["time"].split(":"))
            next_run = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= local:
                next_run += timedelta(days=1)
        rows.append(
            {
                "key": key,
                **spec,
                **config,
                "next_run": next_run,
                "runs": [
                    {
                        "id": r.id,
                        "job_id": r.job_id,
                        "status": r.status,
                        "started_at": r.started_at,
                        "finished_at": r.finished_at,
                        "result": r.result,
                        "error": r.error,
                        "traceback": r.traceback,
                    }
                    for r in runs
                ],
                "recipients": targets
                if key in ("daily_summary", "connection_notifications")
                else [],
                "channel": readiness.channel
                if key in ("daily_summary", "connection_notifications")
                else None,
            }
        )
    await db.commit()
    return {
        "items": rows,
        "timezone": timezone,
        "workers_enabled": bool(get_settings().workers),
        "history_policy": (
            "Up to 10 runs per schedule, reserving 3 recent failures within those 10. "
            "Failures expire after 4 days."
        ),
    }


@router.post("/schedules/{key}/run")
async def run_now(key: str, db: DB) -> dict[str, Any]:
    if key not in CATALOG:
        raise HTTPException(404, "Schedule not found")
    if await db.scalar(
        select(Job.id)
        .where(
            Job.type == "run_schedule",
            Job.status.in_(("queued", "running")),
            Job.payload["schedule_key"].as_string() == key,
        )
        .limit(1)
    ):
        raise HTTPException(409, "This schedule already has a queued or running job")
    if key == "connection_notifications":
        jobs = []
        for incident in await health_issues(db):
            job = await enqueue(
                db,
                "run_schedule",
                {
                    "schedule_key": key,
                    "manual": True,
                    "instance_id": incident["instance_id"],
                    "incident": incident.get("incident"),
                    "issues": incident["issues"],
                },
                max_attempts=3,
            )
            jobs.append(job)
        await db.commit()
        return {"job_ids": jobs}
    job = await enqueue(db, "run_schedule", {"schedule_key": key, "manual": True}, max_attempts=3)
    await db.commit()
    return {"job_ids": [job]}


@router.get("/audit")
async def audit(
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    username: str | None = None,
) -> dict[str, Any]:
    stmt = select(AuditLog)
    count = select(func.count()).select_from(AuditLog)
    if username:
        stmt, count = (
            stmt.where(AuditLog.username == username),
            count.where(AuditLog.username == username),
        )
    rows = await db.scalars(
        stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "method": r.method,
                "path": r.path,
                "status_code": r.status_code,
                "changes": r.changes,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": await db.scalar(count),
        "page": page,
        "page_size": page_size,
    }
