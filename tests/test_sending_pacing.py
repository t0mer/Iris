"""Persistent pacing tests use isolated DBs and no real WhatsApp calls."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.alerts.pacing import pause_sender, reserve
from app.db.models import Job, SendingBudget
from app.jobs import queue
from app.settings_store import set_setting


async def test_sender_and_recipient_spacing_survive_new_sessions(app_client: Any) -> None:
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await reserve(db, "sender", "parent-a", now=now)
    async with factory() as db:
        with pytest.raises(queue.DeferredError) as blocked:
            await reserve(db, "sender", "parent-b", now=now + timedelta(seconds=1))
        assert blocked.value.delay == 29
    async with factory() as db:
        await reserve(db, "sender", "parent-b", now=now + timedelta(seconds=30))
    async with factory() as db:
        with pytest.raises(queue.DeferredError):
            await reserve(db, "sender", "parent-b", now=now + timedelta(seconds=60))
        await reserve(db, "other-sender", "parent-b", now=now + timedelta(seconds=60))


async def test_hourly_daily_limits_defer_without_using_capacity(app_client: Any) -> None:
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await set_setting(db, "alerts.send_hourly_limit", 1)
        await set_setting(db, "alerts.send_daily_limit", 2)
        await db.commit()
        await reserve(db, "sender", "one", now=now)
        with pytest.raises(queue.DeferredError) as blocked:
            await reserve(db, "sender", "two", now=now + timedelta(minutes=1))
        assert blocked.value.delay == 3540
    async with factory() as db:
        await reserve(db, "sender", "two", now=now + timedelta(hours=1))
        with pytest.raises(queue.DeferredError) as blocked:
            await reserve(db, "sender", "three", now=now + timedelta(hours=2))
        assert blocked.value.delay == 22 * 3600
    async with factory() as db:
        budget = await db.get(SendingBudget, "sender")
        assert budget and budget.day_count == 2
        await reserve(db, "sender", "three", now=now + timedelta(days=1))


async def test_queued_wait_does_not_exhaust_retries_or_drop_checkpoints(app_client: Any) -> None:
    factory = app_client.app.state.session_factory
    async with factory() as db:
        jid = await queue.enqueue(
            db, "deliver_alert", {"delivered_recipients": ["one"]}, max_attempts=1
        )
    claimed = await queue.claim(factory)
    assert claimed and claimed.id == jid
    assert await queue.defer(factory, claimed, 120) == "queued"
    assert await queue.claim(factory) is None
    visible = (await app_client.get("/api/jobs?status=queued")).json()
    assert visible[0]["run_after"] and visible[0]["last_error"] == "Waiting for sending capacity"
    async with factory() as db:
        job = await db.get(Job, jid)
        assert job and job.attempts == 0 and job.payload["delivered_recipients"] == ["one"]


async def test_authentication_is_separate_and_cannot_flood_one_contact(app_client: Any) -> None:
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await reserve(db, "openwa:1", "parent", now=now)
        await reserve(db, "greenapi:1", "parent", now=now, authentication=True)
    async with factory() as db:
        with pytest.raises(queue.DeferredError) as blocked:
            await reserve(
                db, "greenapi:1", "parent", now=now + timedelta(seconds=5), authentication=True
            )
        assert blocked.value.delay == 55
        await reserve(
            db, "greenapi:1", "another-parent", now=now + timedelta(seconds=5), authentication=True
        )


async def test_provider_pause_survives_restart_and_covers_all_recipients(app_client: Any) -> None:
    factory = app_client.app.state.session_factory
    async with factory() as db:
        await reserve(db, "sender", "one")
        await pause_sender(db, "sender", 300)
    async with factory() as db:
        with pytest.raises(queue.DeferredError) as blocked:
            await reserve(db, "sender", "two")
        assert blocked.value.delay > 290
        assert len((await db.scalars(select(SendingBudget))).all()) == 2


async def test_real_delivery_defers_second_parent_and_preserves_first_checkpoint(
    app_client: Any,
) -> None:
    import httpx
    import respx
    from sqlalchemy import update

    from app.jobs.worker import run_one
    from tests.test_alerts import MOD_URL, SEND_URL, msg_body, run_all, setup
    from tests.test_webhooks import post
    from tests.test_worker import mod_response

    deps, token, _ = await setup(app_client, recipient="972501234567,972509876543", cooldown=0)
    with respx.mock:
        respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
        send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
        await post(app_client, token, msg_body("text_received_mixed", "PACE1", "threat", 0))
        await run_all(deps)
        assert send.call_count == 1
        async with deps.session_factory() as db:
            job = (await db.scalars(select(Job).where(Job.type == "deliver_alert"))).one()
            assert job.status == "queued" and job.attempts == 0
            assert len(job.payload["delivered_recipients"]) == 1
            past = datetime.now(UTC) - timedelta(seconds=1)
            await db.execute(update(SendingBudget).values(next_allowed=past))
            await db.execute(update(Job).where(Job.id == job.id).values(run_after=past))
            await db.commit()
        claimed = await queue.claim(deps.session_factory)
        assert claimed and await run_one(claimed, deps) == "done"
        assert send.call_count == 2
        bodies = [__import__("json").loads(call.request.content)["chatId"] for call in send.calls]
        assert len(set(bodies)) == 2


async def test_2fa_repeated_requests_are_limited_per_contact_not_only_ip(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.security.two_factor import reserve_green
    from tests.test_two_factor import configure, enable

    await configure(app_client, monkeypatch)
    await enable(app_client)
    monkeypatch.setattr("app.security.two_factor.reserve_green", reserve_green)
    send = AsyncMock()
    monkeypatch.setattr("app.security.two_factor.send_green_code", send)
    app_client.cookies.clear()
    body = {"username": "admin", "password": "correct-horse", "channel": "whatsapp"}
    assert (await app_client.post("/api/auth/login", json=body)).status_code == 200
    response = await app_client.post("/api/auth/login", json=body)
    assert response.status_code == 429 and "use email" in response.json()["detail"]
    assert send.await_count == 1


async def test_explicit_retry_rechecks_rejections_without_repeating_completed_parents(
    app_client: Any,
) -> None:
    factory = app_client.app.state.session_factory
    async with factory() as db:
        job = Job(
            type="deliver_alert",
            status="failed",
            attempts=3,
            payload={"delivered_recipients": ["one"], "rejected_recipients": {"two": 400}},
        )
        db.add(job)
        await db.commit()
        assert await queue.retry_job(db, job.id, manual=True)
        assert job.payload == {"delivered_recipients": ["one"]}
