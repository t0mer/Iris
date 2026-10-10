"""Regression checks for the user's pasted audit; transports remain mocked."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from fastapi import HTTPException
from sqlalchemy import select

from app.alerts.channels import ChannelClient
from app.alerts.recipients import recipients
from app.api import auth
from app.api import stats as stats_api
from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Job, Message, MessageRevision
from app.jobs import handlers, queue
from app.security.two_factor import send_green_code
from app.settings_store import set_setting
from tests.test_alerts import alerts, run_all, setup
from tests.test_pairing import BODY, FORM, routes
from tests.test_parent_recipients import advance_queue
from tests.test_two_factor import configure, enable
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


async def test_five_requests_leave_latest_code_verifiable(app_client, monkeypatch):
    await configure(app_client, monkeypatch)
    await enable(app_client)
    codes = []

    async def deliver(*args):
        codes.append(args[-1])

    monkeypatch.setattr(auth, "deliver", deliver)
    app_client.cookies.clear()
    body = {"username": "admin", "password": "correct-horse"}
    for _ in range(5):
        response = await app_client.post("/api/auth/login", json=body)
        assert response.status_code == 200
    assert (await app_client.post("/api/auth/login", json=body)).status_code == 429
    verified = await app_client.post(
        "/api/auth/verify",
        json={"challenge_id": response.json()["challenge_id"], "code": codes[-1]},
    )
    assert verified.status_code == 200


async def test_failed_code_delivery_releases_request_capacity(app_client, monkeypatch):
    await configure(app_client, monkeypatch)
    await enable(app_client)
    monkeypatch.setattr(auth, "deliver", AsyncMock(side_effect=HTTPException(503, "unavailable")))
    app_client.cookies.clear()
    for _ in range(6):
        response = await app_client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
        )
        assert response.status_code == 503


async def test_https_logout_flags_and_password_bounds(app_client, monkeypatch):
    for field in ("current_password", "new_password"):
        body = {"current_password": "correct-horse", "new_password": "new-password"}
        body[field] = "x" * 257
        assert (await app_client.post("/api/auth/password", json=body)).status_code == 422
    monkeypatch.setattr(get_settings(), "public_base_url", "https://iris.example.com")
    cookie = (await app_client.post("/api/auth/logout")).headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"))
    assert "Max-Age=0" in cookie


@respx.mock
async def test_pairing_completion_is_idempotent(app_client):
    mocked = routes()
    respx.get("https://wa.example/api/sessions/draft-id/webhooks").mock(
        return_value=httpx.Response(200, json=[])
    )
    webhook = respx.post("https://wa.example/api/sessions/draft-id/webhooks").mock(
        return_value=httpx.Response(201, json={"id": "hook"})
    )
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["state"]["status"] = "ready"
    first = await app_client.post(f"/api/pairing/{token}/complete", json=FORM)
    second = await app_client.post(f"/api/pairing/{token}/complete", json=FORM)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len((await app_client.get("/api/instances")).json()) == 1
    assert webhook.call_count == 1


async def test_stale_attempt_rolls_back_pending_writes(app_client):
    factory = app_client.app.state.session_factory
    async with factory() as db:
        jid = await queue.enqueue(db, "process_message", {"message_id": 1})
    claimed = await queue.claim(factory)
    assert claimed and claimed.id == jid
    async with factory() as db:
        row = await db.get(Job, jid)
        row.attempts += 1
        await db.commit()
    async with factory() as db:
        row = await db.get(Job, jid)
        row.last_error = "stale attempt wrote this"
        with pytest.raises(queue.LostLeaseError):
            await queue.ensure_owned(db, claimed)
    async with factory() as db:
        assert (await db.get(Job, jid)).last_error is None


async def test_recovered_same_job_waits_and_fences_old_attempt(app_client):
    from app.jobs.worker import run_one

    deps, _, _ = await setup(app_client)
    async with deps.session_factory() as db:
        await queue.enqueue(db, "process_message", {"message_id": 99})
    first = await queue.claim(deps.session_factory)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(job, deps):
        calls.append(job.attempts)
        if job.attempts == 1:
            started.set()
            await release.wait()
        async with deps.session_factory() as db:
            row = await db.get(Job, job.id)
            row.last_error = f"attempt {job.attempts}"
            await handlers._commit_message(db, job)

    tasks = []
    try:
        tasks.append(asyncio.create_task(run_one(first, deps, {"process_message": handler})))
        await asyncio.wait_for(started.wait(), 5)
        async with deps.session_factory() as db:
            row = await db.get(Job, first.id)
            row.attempts = 2
            await db.commit()
        second = queue.ClaimedJob(first.id, first.type, first.payload, 2, first.max_attempts)
        tasks.append(asyncio.create_task(run_one(second, deps, {"process_message": handler})))
        await asyncio.sleep(0)
        assert calls == [1]
        release.set()
        assert await asyncio.gather(*tasks) == ["superseded", "done"]
        async with deps.session_factory() as db:
            assert (await db.get(Job, first.id)).last_error == "attempt 2"
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await deps.providers.aclose()


async def test_revision_classification_does_not_reuse_current_image(app_client, monkeypatch):
    from app.classify.pipeline import PipelineOutcome

    deps, token, _ = await setup(app_client)
    monkeypatch.setattr(get_settings(), "local_safety_mode", True)
    await post(app_client, token, fx("text_received_mixed"))
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        db.add(
            MessageRevision(
                message_id=message.id, text="old wording", replaced_at=datetime.now(UTC)
            )
        )
        db.add(MessageRevision(message_id=message.id, text="", replaced_at=datetime.now(UTC)))
        await db.commit()
    monkeypatch.setattr(
        handlers,
        "_prepare",
        AsyncMock(return_value=handlers.Prepared(image="data:image/jpeg;base64,current")),
    )
    inputs = []

    async def pipeline(message, ctx):
        inputs.append((message.text, ctx.image_data_url))
        return PipelineOutcome(verdict="safe")

    monkeypatch.setattr(handlers, "run_pipeline", pipeline)
    await run_all(deps)
    assert inputs[0][1] == "data:image/jpeg;base64,current"
    assert inputs[1:] == [("old wording", None)]
    await deps.providers.aclose()


async def test_smtp_accepts_parent_without_whatsapp(monkeypatch):
    assert recipients("Parent@Example.com") == ["email:parent@example.com"]
    send = Mock()
    monkeypatch.setattr("app.alerts.channels.send_email", send)
    client = ChannelClient("smtp", None, {"verified": True}, {}, b"k" * 32)
    await client.send_text("", "email:parent@example.com", "child alert")
    assert send.call_args.args[1:] == ("parent@example.com", "child alert")


async def test_dashboard_today_uses_configured_local_day(app_client, monkeypatch):
    _, token, _ = await setup(app_client)
    body = json.loads(fx("text_received_mixed"))
    body["data"]["timestamp"] = int(datetime(2026, 1, 19, 23, tzinfo=UTC).timestamp())
    await post(app_client, token, json.dumps(body).encode())
    async with app_client.app.state.session_factory() as db:
        await set_setting(db, "alerts.timezone", "Pacific/Kiritimati")
        await db.commit()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 1, 20, 1, tzinfo=UTC)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(stats_api, "datetime", FixedDateTime)
    assert (await app_client.get("/api/stats")).json()["messages_today"] == 1


@respx.mock
async def test_greenapi_approval_has_plain_url():
    base = "https://api.green-api.com/waInstance123"
    respx.get(base + "/getStateInstance/test-token").mock(
        return_value=httpx.Response(200, json={"stateInstance": "authorized"})
    )
    route = respx.post(base + "/sendInteractiveButtons/test-token").mock(
        return_value=httpx.Response(200, json={"idMessage": "sent"})
    )
    link = "https://iris.example.com/verify-contact?token=test"
    await send_green_code(
        {"api_url": "https://api.green-api.com", "instance_id": "123", "token": "test-token"},
        "+15550100101",
        "123456",
        link,
    )
    assert link in json.loads(route.calls[0].request.content)["body"]


@respx.mock
@pytest.mark.parametrize("retry_second", [False, True])
async def test_uncertain_recipient_does_not_block_next_parent(app_client, retry_second):
    deps, token, _ = await setup(app_client, recipient="15550100101,15550100102")
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "telegram",
                "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
                "alerts.recipient_contacts": {
                    "15550100101": {"telegram_chat_id": "111"},
                    "15550100102": {"telegram_chat_id": "222"},
                },
            }
        },
    )
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    targets = []

    def send(request):
        target = json.loads(request.content)["chat_id"]
        targets.append(target)
        if target == "111":
            raise httpx.ReadTimeout("uncertain")
        if retry_second and targets.count("222") == 1:
            return httpx.Response(503, json={"description": "temporary outage"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    respx.post("https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwx/sendMessage").mock(
        side_effect=send
    )
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    await advance_queue(deps)
    await run_all(deps)
    if retry_second:
        await advance_queue(deps)
        await run_all(deps)
    assert targets == (["111", "222", "222"] if retry_second else ["111", "222"])
    alert = (await alerts(app_client))[0]
    assert alert.delivery_status == "partial"
    detail = (await app_client.get(f"/api/alerts/{alert.id}")).json()
    assert {x["status"] for x in detail["recipient_delivery"]} == {"delivered", "uncertain"}
    async with deps.session_factory() as db:
        job = (await db.scalars(select(Job).where(Job.type == "deliver_alert"))).one()
        assert job.payload["uncertain_recipients"] == ["15550100101@c.us"]
    await deps.providers.aclose()
