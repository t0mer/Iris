import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import Job, ScheduleRun
from app.schedules import check_connections, due_schedules, prune_history, tracked
from tests.test_alerts import SEND_URL, run_all, setup


async def test_schedule_catalog_and_manual_run_record_history(app_client: Any) -> None:
    c = app_client
    deps, _, _ = await setup(c)
    catalog = (await c.get("/api/schedules")).json()
    assert {s["key"] for s in catalog["items"]} >= {
        "daily_summary",
        "connections",
        "retention",
        "pairing_cleanup",
    }
    result = await c.post("/api/schedules/recover_jobs/run")
    assert result.status_code == 200 and result.json()["job_ids"]
    await run_all(deps)
    item = next(
        s for s in (await c.get("/api/schedules")).json()["items"] if s["key"] == "recover_jobs"
    )
    assert item["runs"][0]["status"] == "success"
    await deps.providers.aclose()


async def test_history_has_ten_runs_including_three_recent_failures(app_client: Any) -> None:
    c = app_client
    now = datetime.now(UTC)
    async with c.app.state.session_factory() as db:
        for n in range(20):
            db.add(
                ScheduleRun(
                    schedule_key="retention",
                    status="success",
                    started_at=now - timedelta(minutes=20 - n),
                )
            )
        for n in range(5):
            db.add(
                ScheduleRun(
                    schedule_key="retention", status="failed", started_at=now - timedelta(hours=n)
                )
            )
        db.add(
            ScheduleRun(
                schedule_key="retention", status="failed", started_at=now - timedelta(days=5)
            )
        )
        await db.flush()
        await prune_history(db, "retention", now)
        await db.commit()
        runs = list(
            await db.scalars(select(ScheduleRun).where(ScheduleRun.schedule_key == "retention"))
        )
        assert len(runs) == 10
        assert sum(r.status == "failed" for r in runs) == 3
        assert all(r.started_at >= now - timedelta(days=4) for r in runs if r.status == "failed")


async def test_failed_run_keeps_redacted_trace_and_dashboard_warning(app_client: Any) -> None:
    c = app_client
    secret = "123456:abcdefghijklmnopqrstuvwx"
    await c.put("/api/settings", json={"settings": {"alerts.telegram_bot_token": secret}})

    async def fail() -> None:
        raise RuntimeError("provider token " + secret)

    with pytest.raises(RuntimeError):
        await tracked(c.app.state.session_factory, "daily_summary", fail)
    item = next(
        s for s in (await c.get("/api/schedules")).json()["items"] if s["key"] == "daily_summary"
    )
    run = item["runs"][0]
    assert run["status"] == "failed" and "RuntimeError" in run["traceback"]
    assert secret not in json.dumps(run) and "[redacted]" in run["traceback"]
    assert (await c.get("/api/stats")).json()["schedule_failures"]


async def test_daily_schedule_is_once_per_local_day(app_client: Any) -> None:
    c = app_client
    deps, _, _ = await setup(c)
    await c.put(
        "/api/settings",
        json={
            "settings": {"schedules.config": {"daily_summary": {"enabled": True, "time": "20:00"}}}
        },
    )
    now = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)
    await due_schedules(deps, now)
    await due_schedules(deps, now + timedelta(minutes=1))
    async with deps.session_factory() as db:
        jobs = list(
            await db.scalars(
                select(Job).where(
                    Job.type == "run_schedule",
                    Job.payload["schedule_key"].as_string() == "daily_summary",
                )
            )
        )
        assert len(jobs) == 1
    await deps.providers.aclose()


@respx.mock
async def test_connection_failure_notifies_once_then_recovers(app_client: Any) -> None:
    c = app_client
    deps, _, sender_id = await setup(c)
    session = respx.get("https://wa.x/api/sessions/s").mock(
        return_value=httpx.Response(200, json={"status": "disconnected"})
    )
    respx.get("https://wa.x/api/sessions/sender-sess").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    respx.post("https://wa.x/api/sessions/s/start").respond(200, json={"status": "initializing"})
    await check_connections(deps, datetime.now(UTC) - timedelta(minutes=10))
    await check_connections(deps)
    assert (await c.get("/api/stats")).json()["monitoring_issues"]
    await run_all(deps)
    assert send.call_count == 1
    assert "Noa" in json.loads(send.calls[0].request.content)["text"]
    from app.alerts.format import is_own_alert

    assert is_own_alert(json.loads(send.calls[0].request.content)["text"], deps.key_bytes)
    session.mock(return_value=httpx.Response(200, json={"status": "ready"}))
    from app.config import get_settings
    from app.db.models import Instance
    from app.openwa.client import WEBHOOK_EVENTS

    async with deps.session_factory() as db:
        child = await db.scalar(select(Instance).where(Instance.id != sender_id))
        expected = f"{get_settings().webhook_url_base}/webhooks/{child.webhook_token}"
    respx.get("https://wa.x/api/sessions/s/webhooks").mock(
        return_value=httpx.Response(
            200, json={"data": [{"url": expected, "events": list(WEBHOOK_EVENTS)}]}
        )
    )
    from app.api.instances import save_webhook_status

    async with deps.session_factory() as db:
        await save_webhook_status(db, child.id, "registered", None)
    await check_connections(deps)
    assert not (await c.get("/api/stats")).json()["monitoring_issues"]
    await deps.providers.aclose()


@respx.mock
async def test_connection_retry_policy_is_persistent_bounded_and_delays_notifications(
    app_client: Any,
) -> None:
    from app.db.models import Setting

    c = app_client
    deps, _, _ = await setup(c)
    config = {"connections": {"retry_count": 2, "retry_wait_minutes": 3, "notify_wait_minutes": 10}}
    result = await c.put("/api/settings", json={"settings": {"schedules.config": config}})
    assert result.status_code == 200
    respx.get("https://wa.x/api/sessions/s").respond(200, json={"status": "disconnected"})
    respx.get("https://wa.x/api/sessions/sender-sess").respond(200, json={"status": "ready"})
    refresh = respx.post("https://wa.x/api/sessions/s/start").respond(503, json={"message": "busy"})
    start = datetime.now(UTC) - timedelta(minutes=10)
    for minute, attempts in [(0, 1), (2, 1), (3, 2), (9, 2)]:
        await check_connections(deps, start + timedelta(minutes=minute))
        assert refresh.call_count == attempts
        async with deps.session_factory() as db:
            queued = list(await db.scalars(select(Job).where(Job.type == "run_schedule")))
            assert not [
                j for j in queued if j.payload.get("schedule_key") == "connection_notifications"
            ]
            recovery = await db.scalar(
                select(Setting).where(Setting.key.like("internal.connection_recovery.%"))
            )
            assert recovery.value["attempts"] == attempts
    await check_connections(deps, start + timedelta(minutes=10))
    await check_connections(deps, start + timedelta(minutes=11))
    assert refresh.call_count == 2
    async with deps.session_factory() as db:
        queued = list(await db.scalars(select(Job).where(Job.type == "run_schedule")))
        assert (
            len([j for j in queued if j.payload.get("schedule_key") == "connection_notifications"])
            == 1
        )
    issues = (await c.get("/api/stats")).json()["monitoring_issues"]
    assert issues[0]["refresh_attempts"] == 2 and "503" in issues[0]["refresh_error"]
    await deps.providers.aclose()


@respx.mock
async def test_auto_refresh_recovery_clears_dashboard_without_parent_alert(app_client: Any) -> None:
    from app.config import get_settings
    from app.db.models import Instance
    from app.openwa.client import WEBHOOK_EVENTS

    c = app_client
    deps, _, sender_id = await setup(c)
    async with deps.session_factory() as db:
        child = await db.scalar(select(Instance).where(Instance.id != sender_id))
        expected = f"{get_settings().webhook_url_base}/webhooks/{child.webhook_token}"
    from app.api.instances import save_webhook_status

    async with deps.session_factory() as db:
        await save_webhook_status(db, child.id, "registered", None)
    respx.get("https://wa.x/api/sessions/s").mock(
        side_effect=[
            httpx.Response(200, json={"status": "disconnected"}),
            httpx.Response(200, json={"status": "ready"}),
        ]
    )
    respx.get("https://wa.x/api/sessions/sender-sess").respond(200, json={"status": "ready"})
    refresh = respx.post("https://wa.x/api/sessions/s/start").respond(
        200, json={"status": "initializing"}
    )
    respx.get("https://wa.x/api/sessions/s/webhooks").respond(
        200, json={"data": [{"url": expected, "events": WEBHOOK_EVENTS}]}
    )
    await check_connections(deps)
    assert refresh.call_count == 1
    assert not (await c.get("/api/stats")).json()["monitoring_issues"]
    async with deps.session_factory() as db:
        queued = list(await db.scalars(select(Job).where(Job.type == "run_schedule")))
        assert not [
            j for j in queued if j.payload.get("schedule_key") == "connection_notifications"
        ]
    await deps.providers.aclose()


async def test_audit_tracks_before_after_and_never_credentials(app_client: Any) -> None:
    c = app_client
    await c.put("/api/settings", json={"settings": {"alerts.cooldown_minutes": 15}})
    await c.put(
        "/api/settings",
        json={"settings": {"alerts.cooldown_minutes": 20, "openai.api_key": "sk-sensitive-test"}},
    )
    actions = (await c.get("/api/audit")).json()["items"]
    change = next(
        x
        for a in actions
        for x in a["changes"]
        if x.get("id") == "alerts.cooldown_minutes" and x.get("before") == 15
    )
    assert change["after"] == 20
    assert "sk-sensitive-test" not in json.dumps(actions)
    assert any(a["username"] == "admin" for a in actions)
    await c.put("/api/settings", json={"settings": {"bad-setting": True}})
    assert (await c.get("/api/audit")).json()["items"][0]["status_code"] == 422


@respx.mock
async def test_daily_summary_only_contains_assigned_children(app_client: Any) -> None:
    c = app_client
    deps, _, _ = await setup(c)
    await c.post(
        "/api/instances",
        json={
            "kid_name": "Other child",
            "openwa_base_url": "https://wa.x",
            "openwa_instance_id": "other",
        },
    )
    await c.put(
        "/api/settings", json={"settings": {"alerts.recipient_children": {"972501234567": [1]}}}
    )
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    await c.post("/api/schedules/daily_summary/run")
    await run_all(deps)
    text = json.loads(send.calls[0].request.content)["text"]
    assert "Noa" in text and "Other child" not in text
    await deps.providers.aclose()
