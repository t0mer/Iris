"""Application schedules, durable execution history and operational notifications."""

import asyncio
import re
import traceback
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Alert, Instance, Job, Message, MessageReceipt, ScheduleRun, Setting
from app.jobs.queue import ClaimedJob, DeferredError, enqueue
from app.settings_store import get_secret, get_setting

if TYPE_CHECKING:
    from app.jobs.handlers import Deps

CATALOG: dict[str, dict[str, Any]] = {
    "provider_health": {
        "name": "Provider health checks",
        "interval": 60,
        "enabled": True,
        "description": (
            "Check configured AI and notification providers. Down and recovery alerts are "
            "limited to once per provider per hour or the interval set in Providers."
        ),
    },
    "openwa_recovery": {
        "name": "OpenWA message catch-up",
        "interval": 60,
        "enabled": True,
        "description": (
            "Apply webhook retry settings and recover missed messages "
            "from retained OpenWA history without duplicates."
        ),
    },
    "review_responses": {
        "name": "Parent alert responses",
        "interval": 30,
        "enabled": True,
        "description": (
            "Check GreenAPI and Telegram review buttons. First accepted response wins; "
            "later responses are recorded in notes."
        ),
    },
    "daily_summary": {
        "name": "Daily summary",
        "interval": None,
        "enabled": False,
        "description": "Daily counts for assigned children, sent to eligible selected parents.",
    },
    "connections": {
        "name": "Device and webhook verification",
        "interval": 60,
        "enabled": True,
        "description": (
            "Verify devices and webhooks. Refresh disconnected sessions using the retry "
            "policy; notify parents after the configured offline wait."
        ),
    },
    "connection_notifications": {
        "name": "Device failure notifications",
        "interval": None,
        "enabled": True,
        "description": "Notify selected parents of new incidents, respecting child assignments.",
    },
    "retention": {
        "name": "Message and alert retention",
        "interval": 3600,
        "enabled": True,
        "description": "Remove expired data. Preserve unresolved reviews and retained alerts.",
    },
    "media_cleanup": {
        "name": "Media retention and deletion",
        "interval": 60,
        "enabled": True,
        "description": "Remove expired or explicitly deleted saved media from local or S3 storage.",
    },
    "recover_jobs": {
        "name": "Recover stalled jobs",
        "interval": 60,
        "enabled": True,
        "description": "Recover expired worker leases so interrupted jobs can continue.",
    },
    "pending_alerts": {
        "name": "Pending alert catch-up",
        "interval": 60,
        "enabled": True,
        "description": "Resume held alerts without broadcasting the historical review backlog.",
    },
    "group_names": {
        "name": "Resolve group names",
        "interval": 60,
        "enabled": True,
        "description": "Fetch names for unnamed WhatsApp groups.",
    },
    "pairing_cleanup": {
        "name": "Expired pairing cleanup",
        "interval": 15,
        "enabled": True,
        "description": "Delete abandoned temporary pairings and expired completion receipts.",
    },
}
_locks: dict[str, asyncio.Lock] = {}


async def prune_history(db: AsyncSession, key: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    rows = list(
        await db.scalars(
            select(ScheduleRun)
            .where(ScheduleRun.schedule_key == key)
            .order_by(ScheduleRun.id.desc())
        )
    )
    failures = [
        r for r in rows if r.status == "failed" and r.started_at >= now - timedelta(days=4)
    ][:3]
    others = [r for r in rows if r.status != "failed"][: 10 - len(failures)]
    keep = {r.id for r in (*failures, *others)}
    discarded = [r.id for r in rows if r.id not in keep]
    if discarded:
        await db.execute(delete(ScheduleRun).where(ScheduleRun.id.in_(discarded)))


async def redact_error(db: AsyncSession, text: str) -> str:
    from app.settings_store import REGISTRY

    cfg = get_settings()
    secrets = [
        cfg.secret_key,
        cfg.admin_password,
        cfg.openwa_api_key,
        cfg.whisper_api_key,
        cfg.telegram_bot_token,
        cfg.greenapi_token,
        cfg.smtp_password,
    ]
    for key, spec in REGISTRY.items():
        if spec.secret:
            secrets.append(await get_secret(db, key, cfg.key_bytes))
    from app.security.two_factor import green_api_config, smtp_config

    secrets += [
        (await green_api_config(db, cfg)).get("token"),
        (await smtp_config(db, cfg)).get("password"),
    ]
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(https?://[^\s/]+/(?:bot|waInstance)[^\s]+)", "[provider URL redacted]", text)
    return text[:24000]


async def tracked(
    factory: async_sessionmaker[AsyncSession], key: str, callback: Any, job_id: int | None = None
) -> Any:
    async with _locks.setdefault(key, asyncio.Lock()):
        async with factory() as db:
            run = ScheduleRun(schedule_key=key, job_id=job_id)
            db.add(run)
            await db.flush()
            rid = run.id
            await prune_history(db, key)
            await db.commit()
        status, result, error, trace = "success", None, None, None
        try:
            result = await callback()
            if key == "review_responses" and result.get("issues"):
                status, error = "partial", " ".join(result["issues"])
            if key == "openwa_recovery" and result.get("errors"):
                status = "partial"
                error = (
                    f"OpenWA catch-up unavailable for {len(result['errors'])} phone(s); will retry."
                )
            return result
        except DeferredError as exc:
            status, error = "waiting", str(exc)
            raise
        except asyncio.CancelledError:
            status, error = "interrupted", "Application stopped before the run completed."
            raise
        except Exception as exc:
            status = "failed"
            async with factory() as db:
                error = await redact_error(db, str(exc))
                trace = await redact_error(db, traceback.format_exc())
            raise
        finally:
            async with factory() as db:
                completed_run = await db.get(ScheduleRun, rid)
                if completed_run:
                    (
                        completed_run.status,
                        completed_run.result,
                        completed_run.error,
                        completed_run.traceback,
                    ) = status, result, error, trace
                    completed_run.finished_at = datetime.now(UTC)
                    await prune_history(db, key)
                    await db.commit()


async def schedule_config(db: AsyncSession, key: str) -> dict[str, Any]:
    saved = await get_setting(db, "schedules.config")
    return {
        "enabled": CATALOG[key]["enabled"],
        "interval": CATALOG[key]["interval"],
        "time": "20:00",
        **(
            {"retry_count": 1, "retry_wait_minutes": 10, "notify_wait_minutes": 10}
            if key == "connections"
            else {}
        ),
        **saved.get(key, {}),
    }


async def due_schedules(deps: "Deps", now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    async with deps.session_factory() as db:
        timezone = ZoneInfo(str(await get_setting(db, "alerts.timezone")))
        local = now.astimezone(timezone)
        for key in CATALOG:
            await prune_history(db, key, now)
            if key in ("pairing_cleanup", "connection_notifications"):
                continue
            config = await schedule_config(db, key)
            if not config["enabled"]:
                continue
            state_key = "internal.schedule_due." + key
            state = await db.get(Setting, state_key)
            last = state.value if state else {}
            if key == "daily_summary":
                if (
                    local.strftime("%H:%M") < config["time"]
                    or last.get("day") == local.date().isoformat()
                ):
                    continue
            elif last.get("at") and now.timestamp() - last["at"] < config["interval"]:
                continue
            if await db.scalar(
                select(Job.id)
                .where(
                    Job.type == "run_schedule",
                    Job.status.in_(("queued", "running")),
                    Job.payload["schedule_key"].as_string() == key,
                )
                .limit(1)
            ):
                continue
            await enqueue(db, "run_schedule", {"schedule_key": key}, max_attempts=3)
            value = {"at": now.timestamp(), "day": local.date().isoformat()}
            if state:
                state.value = value
            else:
                db.add(Setting(key=state_key, value=value))
        await db.commit()


async def health_issues(db: AsyncSession) -> list[dict[str, Any]]:
    roles = await get_setting(db, "phones.roles")
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    items = []
    for inst in await db.scalars(select(Instance).where(Instance.enabled.is_(True))):
        if roles.get(str(inst.id)) == "parent" or inst.id == sender_id:
            continue
        row = await db.get(Setting, f"internal.monitoring_health.{inst.id}")
        if row and row.value.get("issues"):
            items.append({"instance_id": inst.id, "kid_name": inst.kid_name, **row.value})
        else:
            webhook = await db.get(Setting, f"internal.webhook_status.{inst.id}")
            if webhook and webhook.value.get("status") == "failed":
                items.append(
                    {
                        "instance_id": inst.id,
                        "kid_name": inst.kid_name,
                        "issues": [webhook.value.get("error") or "Webhook registration failed"],
                    }
                )
    return items


async def check_connections(deps: "Deps", now: datetime | None = None) -> dict[str, Any]:
    from urllib.parse import quote

    from app.monitoring import probe_instance, session_details
    from app.openwa.client import WEBHOOK_EVENTS, OpenWAClient, OpenWAError
    from app.security.crypto import decrypt

    cfg = get_settings()
    now = now or datetime.now(UTC)
    async with deps.session_factory() as db:
        policy = await schedule_config(db, "connections")
        refreshes = 0
        roles = await get_setting(db, "phones.roles")
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        instances = list(await db.scalars(select(Instance)))
        count = 0
        for inst in instances:
            if inst.id == sender_id:
                await probe_instance(inst, deps.key_bytes)
            if not inst.enabled or roles.get(str(inst.id)) == "parent" or inst.id == sender_id:
                continue
            count += 1
            await probe_instance(inst, deps.key_bytes)
            issues = []
            status = session_details[inst.id][0]
            recovery_key = f"internal.connection_recovery.{inst.id}"
            recovery_row = await db.get(Setting, recovery_key)
            recovery = dict(recovery_row.value if recovery_row else {})
            if status == "ready":
                recovery = {}
            else:
                recovery.setdefault("offline_since", now.timestamp())
                recovery.setdefault("attempts", 0)
                due = (
                    now.timestamp() - recovery.get("last_attempt", 0)
                    >= policy["retry_wait_minutes"] * 60
                )
                if (
                    status in ("disconnected", "failed")
                    and inst.openwa_api_key_enc
                    and due
                    and recovery["attempts"] < policy["retry_count"]
                ):
                    recovery["attempts"] += 1
                    recovery["last_attempt"] = now.timestamp()
                    if recovery_row is None:
                        recovery_row = Setting(key=recovery_key, value=dict(recovery))
                        db.add(recovery_row)
                    else:
                        recovery_row.value = dict(recovery)
                    # Reserve before the external request: even an uncertain outcome counts once.
                    await db.commit()
                    refreshes += 1
                    client = OpenWAClient(
                        inst.openwa_base_url, decrypt(deps.key_bytes, inst.openwa_api_key_enc)
                    )
                    try:
                        await client._request(
                            "POST", f"/api/sessions/{quote(inst.openwa_instance_id, safe='')}/start"
                        )
                        recovery["last_error"] = None
                    except OpenWAError as exc:
                        recovery["last_error"] = (
                            f"Automatic refresh failed (HTTP {exc.status or 'unreachable'})."
                        )
                    finally:
                        await client.aclose()
                    await probe_instance(inst, deps.key_bytes)
                    status = session_details[inst.id][0]
                    if status == "ready":
                        recovery = {}
            if recovery_row is None:
                recovery_row = Setting(key=recovery_key, value=dict(recovery))
                db.add(recovery_row)
            else:
                recovery_row.value = dict(recovery)
            notify_after = (
                recovery.get("offline_since", now.timestamp()) + policy["notify_wait_minutes"] * 60
            )
            connection_notification_due = status == "ready" or now.timestamp() >= notify_after
            if status != "ready":
                issues.append("WhatsApp connection is " + status)
            if status == "ready" and inst.openwa_api_key_enc:
                client = OpenWAClient(
                    inst.openwa_base_url, decrypt(deps.key_bytes, inst.openwa_api_key_enc)
                )
                try:
                    response = await client._request(
                        "GET", f"/api/sessions/{quote(inst.openwa_instance_id, safe='')}/webhooks"
                    )
                    items = (
                        response.get("data", response) if isinstance(response, dict) else response
                    )
                    expected = f"{cfg.webhook_url_base}/webhooks/{inst.webhook_token}"
                    webhook = (
                        next(
                            (w for w in items if isinstance(w, dict) and w.get("url") == expected),
                            None,
                        )
                        if isinstance(items, list)
                        else None
                    )
                    if not webhook:
                        issues.append("Iris webhook is missing or points to an invalid destination")
                    elif not set(WEBHOOK_EVENTS).issubset(set(webhook.get("events", []))):
                        issues.append("Iris webhook is missing required message events")
                except OpenWAError:
                    issues.append("Webhook registration could not be verified")
                finally:
                    await client.aclose()
            saved = await db.get(Setting, f"internal.webhook_status.{inst.id}")
            if saved and saved.value.get("status") == "failed":
                issues.append("Webhook registration failed; register it again in Phones")
            health_key = f"internal.monitoring_health.{inst.id}"
            state = await db.get(Setting, health_key)
            old = state.value if state else {}
            changed = issues and (
                not old.get("issues")
                or old.get("connection_status") == "ready"
                or (status == "ready" and issues != old.get("issues"))
            )
            incident = old.get("incident", 0) + int(bool(changed))
            value = {
                "issues": issues,
                "connection_status": status,
                "checked_at": datetime.now(UTC).isoformat(),
                "incident": incident,
                "refresh_attempts": recovery.get("attempts", 0),
                "refresh_limit": policy["retry_count"],
                "refresh_error": recovery.get("last_error"),
                "notify_after": datetime.fromtimestamp(notify_after, UTC).isoformat()
                if status != "ready"
                else None,
            }
            if state:
                state.value = value
            else:
                db.add(Setting(key=health_key, value=value))
            if (
                issues
                and connection_notification_due
                and (
                    status == "ready"
                    and issues != old.get("issues")
                    or status != "ready"
                    and not recovery.get("notified")
                )
                and (await schedule_config(db, "connection_notifications"))["enabled"]
            ):
                if status != "ready":
                    recovery["notified"] = True
                    recovery_row.value = dict(recovery)
                await enqueue(
                    db,
                    "run_schedule",
                    {
                        "schedule_key": "connection_notifications",
                        "instance_id": inst.id,
                        "incident": incident,
                        "issues": issues,
                    },
                    max_attempts=3,
                )
        await db.commit()
        return {
            "checked_children": count,
            "refresh_attempts": refreshes,
            "incidents": len(await health_issues(db)),
        }


async def notification(job: ClaimedJob, deps: "Deps", daily: bool) -> dict[str, Any]:
    from app.alerts.delivery import send_to_parents
    from app.alerts.format import with_signed_dashboard
    from app.alerts.readiness import delivery_readiness
    from app.jobs.queue import PermanentError

    async with deps.session_factory() as db:
        readiness = await delivery_readiness(db, job.payload.get("channel"))
        if not readiness.ready:
            raise PermanentError(readiness.error)
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        sender = await db.get(Instance, sender_id) if sender_id else None
        assignments = await get_setting(db, "alerts.recipient_children")
        roles = await get_setting(db, "phones.roles")
        children = {
            i.id: i.kid_name
            for i in await db.scalars(select(Instance))
            if roles.get(str(i.id)) != "parent" and i.id != sender_id
        }
        child_id = int(job.payload.get("instance_id") or 0)
        if not daily:
            if child_id not in children:
                return {"skipped": "Child was removed"}
            current = await db.get(Setting, f"internal.monitoring_health.{child_id}")
            if (
                current
                and current.value.get("notify_after")
                and not job.payload.get("manual")
                and datetime.now(UTC) < datetime.fromisoformat(current.value["notify_after"])
            ):
                return {"skipped": "Device recovery grace period"}
            if current and (
                not current.value.get("issues")
                or current.value.get("incident") != job.payload.get("incident")
            ):
                return {"skipped": "Incident recovered or was replaced"}
        targets = job.payload.get("recipients", [r.target for r in readiness.recipients])
        targets = [
            t
            for t in targets
            if t not in assignments
            or (set(assignments[t]) & (set(children) if daily else {child_id}))
        ]
        if not targets:
            return {"skipped": "No assigned recipients"}
        completed = list(job.payload.get("delivered_recipients", []))
        if daily and "window_end" not in job.payload:
            job.payload["window_end"] = datetime.now(UTC).isoformat()
        errors = []
        # Each parent's summary contains only their assigned children.
        for target in targets:
            if target in completed:
                continue
            if daily:
                names = assignments.get(target, list(children))
                window_end = datetime.fromisoformat(job.payload["window_end"])
                since = window_end - timedelta(days=1)
                lines = []
                for iid in names:
                    if iid not in children:
                        continue
                    mids = select(MessageReceipt.message_id).where(
                        MessageReceipt.instance_id == iid
                    )
                    messages = await db.scalar(
                        select(func.count())
                        .select_from(Message)
                        .where(
                            Message.id.in_(mids),
                            Message.sent_at >= since,
                            Message.sent_at <= window_end,
                        )
                    )
                    alerts = await db.scalar(
                        select(func.count())
                        .select_from(Alert)
                        .where(
                            Alert.message_id.in_(mids),
                            Alert.created_at >= since,
                            Alert.created_at <= window_end,
                        )
                    )
                    lines.append(f"{children[iid]}: {messages} messages, {alerts} alerts")
                text = "Iris daily summary (last 24 hours)\n" + "\n".join(lines)
            else:
                text = f"Iris monitoring problem for {children[child_id]}\n" + "\n".join(
                    job.payload.get("issues", [])
                )
            text = with_signed_dashboard(text, deps.public_base_url, deps.key_bytes)
            job.payload["recipients"] = [target]
            try:
                await send_to_parents(
                    db, job, sender, deps.key_bytes, text, await get_setting(db, "alerts.recipient")
                )
            except PermanentError as exc:
                errors.append(str(exc))
            finally:
                completed = list(job.payload.get("delivered_recipients", []))
                job.payload["recipients"] = targets
                stored = await db.get(Job, job.id)
                if stored:
                    stored.payload = dict(job.payload)
                    await db.commit()
        if errors:
            raise PermanentError("; ".join(errors))
        return {"delivered_recipients": len(completed), "recipients": len(targets)}


async def run_schedule(job: ClaimedJob, deps: "Deps") -> None:
    key = job.payload.get("schedule_key")
    if key not in CATALOG:
        from app.jobs.queue import PermanentError

        raise PermanentError("Unknown schedule")

    async def operation() -> Any:
        async with deps.session_factory() as db:
            config = await schedule_config(db, key)
        if not config["enabled"] and not job.payload.get("manual"):
            return {"skipped": "Schedule disabled before execution"}
        if key == "review_responses":
            from app.alerts.actions import poll

            return await poll(deps.session_factory)
        if key == "openwa_recovery":
            from app.openwa.recovery import recover

            return await recover(
                deps.session_factory, deps.key_bytes, manual=bool(job.payload.get("manual"))
            )
        if key == "connections":
            return await check_connections(deps)
        if key == "provider_health":
            from app.provider_health import monitor

            return await monitor(deps)
        if key in ("daily_summary", "connection_notifications"):
            return await notification(job, deps, key == "daily_summary")
        if key == "retention":
            from app.retention import run_retention

            return await run_retention(deps.session_factory)
        if key == "recover_jobs":
            from app.jobs.queue import recover_stale

            return {"recovered": await recover_stale(deps.session_factory)}
        if key == "media_cleanup":
            from app.media.sweep import sweep_media

            return {
                "removed": await sweep_media(deps.session_factory, deps.key_bytes, deps.data_dir)
            }
        if key == "group_names":
            from app.chats import resolve_group_names

            await resolve_group_names(deps.session_factory, deps.key_bytes)
            return {"completed": True}
        if key == "pending_alerts":
            from app.alerts.service import notify_pending_reviews

            async with deps.session_factory() as db:
                await notify_pending_reviews(db)
            return {"completed": True}
        if key == "pairing_cleanup":
            from app.api.pairing import cleanup_once

            await cleanup_once(deps.session_factory)
            return {"completed": True}

    await tracked(deps.session_factory, key, operation, job.id)
