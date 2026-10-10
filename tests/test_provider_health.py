from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import Job, Setting
from app.jobs.queue import ClaimedJob
from app.provider_health import PREFIX, deliver_notice, probe_providers, record_health
from app.settings_store import set_setting


async def test_outage_and_recovery_have_durable_hourly_limit(app_client):  # type: ignore[no-untyped-def]
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await record_health(db, {"openwa": ("OpenWA", True, None)}, now)
        assert not list(await db.scalars(select(Job).where(Job.type == "provider_notice")))
        await record_health(
            db, {"openwa": ("OpenWA", False, "ReadTimeout")}, now + timedelta(seconds=10)
        )
        await record_health(
            db, {"openwa": ("OpenWA", False, "ReadTimeout")}, now + timedelta(minutes=20)
        )
        jobs = list(await db.scalars(select(Job).where(Job.type == "provider_notice")))
        assert len(jobs) == 1 and jobs[0].payload["status"] == "down"
        assert jobs[0].max_attempts == 1
    # Recreate a DB session: restarting Iris does not reset the limit.
    async with factory() as db:
        await record_health(db, {"openwa": ("OpenWA", True, None)}, now + timedelta(minutes=30))
        assert len(list(await db.scalars(select(Job).where(Job.type == "provider_notice")))) == 1
        await record_health(db, {"openwa": ("OpenWA", True, None)}, now + timedelta(minutes=61))
        jobs = list(await db.scalars(select(Job).where(Job.type == "provider_notice")))
        assert len(jobs) == 2 and jobs[-1].payload["status"] == "up"
        await record_health(db, {"openwa": ("OpenWA", True, None)}, now + timedelta(hours=3))
        assert len(list(await db.scalars(select(Job).where(Job.type == "provider_notice")))) == 2


async def test_interval_validation_and_schedule_config_are_separate(app_client):  # type: ignore[no-untyped-def]
    c = app_client
    assert (
        await c.put(
            "/api/settings", json={"settings": {"alerts.provider_notification_minutes": 59}}
        )
    ).status_code == 422
    assert (
        await c.put(
            "/api/settings",
            json={
                "settings": {
                    "alerts.provider_notification_minutes": 180,
                    "schedules.config": {"provider_health": {"interval": 120}},
                }
            },
        )
    ).status_code == 200
    values = (await c.get("/api/settings")).json()
    assert values["alerts.provider_notification_minutes"] == 180
    schedule = next(
        i for i in (await c.get("/api/schedules")).json()["items"] if i["key"] == "provider_health"
    )
    assert schedule["interval"] == 120
    c.cookies.clear()
    assert (await c.get("/api/settings/provider-health")).status_code == 401


@respx.mock
async def test_telegram_health_is_read_only_and_redacts_secret_from_errors(app_client):  # type: ignore[no-untyped-def]
    from app.config import get_settings

    token = "123456:abcdefghijklmnopqrstuvwxyz"
    async with app_client.app.state.session_factory() as db:
        await set_setting(db, "alerts.telegram_bot_token", token, get_settings().key_bytes)
        route = respx.get(f"https://api.telegram.org/bot{token}/getMe").mock(
            return_value=httpx.Response(401, json={"description": token})
        )
        result = await probe_providers(db)
        assert route.called and result["telegram"] == ("Telegram", False, "HTTP 401")
        assert token not in str(result)
        assert not any(call.request.method == "POST" for call in respx.calls)


async def test_unconfigured_provider_is_removed_from_dashboard(app_client):  # type: ignore[no-untyped-def]
    async with app_client.app.state.session_factory() as db:
        await record_health(db, {"telegram": ("Telegram", False, "HTTP 401")}, datetime.now(UTC))
        await record_health(db, {}, datetime.now(UTC))
        assert await db.get(Setting, PREFIX + "telegram") is None


@respx.mock
async def test_whisper_checks_authenticated_models_instead_of_nonexistent_health(
    app_client, monkeypatch
):  # type: ignore[no-untyped-def]
    from app.config import get_settings

    cfg = get_settings().model_copy(
        update={
            "whisper_url": "http://whisper:8000/v1/audio/transcriptions",
            "whisper_api_key": "private-test-key",
        }
    )
    monkeypatch.setattr("app.provider_health.get_settings", lambda: cfg)
    route = respx.get("http://whisper:8000/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "whisper"}]})
    )
    async with app_client.app.state.session_factory() as db:
        result = await probe_providers(db)
        assert result["whisper"] == ("Whisper", True, None)
        assert route.calls.last.request.headers["Authorization"] == "Bearer private-test-key"
        route.mock(return_value=httpx.Response(401))
        assert (await probe_providers(db))["whisper"] == ("Whisper", False, "HTTP 401")


async def test_system_recipients_are_independent_of_parents_and_child_assignments(app_client):  # type: ignore[no-untyped-def]
    from app.alerts.readiness import delivery_readiness
    from app.security.two_factor import CONFIG_KEY
    from tests.test_alert_readiness import parent, provider

    user_id = await parent(app_client, "system-admin")
    await provider(app_client, CONFIG_KEY)
    target = "email:system-admin@example.com"
    saved = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.system_recipient": target,
                "alerts.provider_notification_channel": "smtp",
            }
        },
    )
    assert saved.status_code == 200, saved.text
    values = (await app_client.get("/api/settings")).json()
    assert values["alerts.recipient"] is None
    async with app_client.app.state.session_factory() as db:
        await set_setting(db, "alerts.recipient_children", {target: []})
        readiness = await delivery_readiness(
            db,
            "smtp",
            {
                "alerts.recipient": values["alerts.system_recipient"],
                "alerts.recipient_channels": {},
                "alerts.recipient_children": {},
                "alerts.recipient_contacts": {},
            },
        )
        assert readiness.eligible_targets == [target]
    rejected = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.system_recipient": target,
                "alerts.provider_notification_channel": "telegram",
            }
        },
    )
    assert rejected.status_code == 422
    assert (await app_client.delete(f"/api/users/{user_id}")).status_code == 204
    async with app_client.app.state.session_factory() as db:
        readiness = await delivery_readiness(
            db,
            "smtp",
            {
                "alerts.recipient": target,
                "alerts.recipient_channels": {},
                "alerts.recipient_children": {},
                "alerts.recipient_contacts": {},
            },
        )
        assert not readiness.eligible_targets
        assert "deleted" in readiness.recipients[0].reason


@pytest.mark.parametrize("uncertain", [False, True])
async def test_operational_notice_uses_healthy_explicit_channel_and_checkpoints(
    app_client, monkeypatch, uncertain
):  # type: ignore[no-untyped-def]
    from app.alerts.readiness import DeliveryReadiness, RecipientReadiness
    from app.config import get_settings

    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await set_setting(db, "alerts.provider_notification_channel", "telegram")
        await record_health(
            db,
            {"openwa": ("OpenWA", False, "ReadTimeout"), "telegram": ("Telegram", True, None)},
            now,
        )
        stored = await db.scalar(select(Job).where(Job.type == "provider_notice"))
        job = ClaimedJob(stored.id, stored.type, dict(stored.payload), 1, 1)
    recipient = RecipientReadiness(
        "email:parent@example.com", 1, "Parent", True, None, destination="123", channel="telegram"
    )
    monkeypatch.setattr(
        "app.provider_health.delivery_readiness",
        AsyncMock(return_value=DeliveryReadiness("telegram", True, None, [recipient])),
    )
    client = SimpleNamespace(sender_key="telegram:test", send_text=AsyncMock(), aclose=AsyncMock())
    if uncertain:
        from app.openwa.client import OpenWAError

        client.send_text.side_effect = OpenWAError(None, "Delivery uncertain")
    build = AsyncMock(return_value=client)
    monkeypatch.setattr("app.provider_health.build_client", build)
    monkeypatch.setattr("app.provider_health.reserve", AsyncMock())
    deps = SimpleNamespace(session_factory=factory, key_bytes=get_settings().key_bytes)
    await deliver_notice(job, deps)
    await deliver_notice(job, deps)
    duplicate = ClaimedJob(job.id + 1000, job.type, {"provider": "openwa", "status": "down"}, 1, 1)
    await deliver_notice(duplicate, deps)
    assert client.send_text.await_count == 1
    assert build.await_args.args[3] == "telegram"
    assert "OpenWA is unavailable" in client.send_text.await_args.args[2]
    assert job.payload["attempted_recipients"] == ["email:parent@example.com"]
    if not uncertain:
        assert job.payload["delivered_recipients"] == ["email:parent@example.com"]
    async with factory() as db:
        row = await db.get(Setting, PREFIX + "openwa")
        assert row.value["delivered_count"] == (0 if uncertain else 1)


async def test_pacing_defers_system_notice_and_retry_sends_only_unsent_recipients(
    app_client, monkeypatch
):  # type: ignore[no-untyped-def]
    from app.alerts.readiness import DeliveryReadiness, RecipientReadiness
    from app.config import get_settings
    from app.jobs.queue import DeferredError

    factory = app_client.app.state.session_factory
    async with factory() as db:
        await set_setting(db, "alerts.provider_notification_channel", "telegram")
        await record_health(db, {"openwa": ("OpenWA", False, "ReadTimeout")}, datetime.now(UTC))
        stored = await db.scalar(select(Job).where(Job.type == "provider_notice"))
        job = ClaimedJob(stored.id, stored.type, dict(stored.payload), 1, 1)
    recipients = [
        RecipientReadiness(target, None, target, True, None, destination=target, channel="telegram")
        for target in ["email:first@example.com", "email:second@example.com"]
    ]
    monkeypatch.setattr(
        "app.provider_health.delivery_readiness",
        AsyncMock(return_value=DeliveryReadiness("telegram", True, None, recipients)),
    )
    client = SimpleNamespace(sender_key="test", send_text=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr("app.provider_health.build_client", AsyncMock(return_value=client))
    reservations = 0

    async def paced(db, *_args):  # type: ignore[no-untyped-def]
        nonlocal reservations
        reservations += 1
        if reservations == 2:
            await db.rollback()  # The real pacing helper expires ORM objects on deferral.
            raise DeferredError("Wait", 30)

    monkeypatch.setattr("app.provider_health.reserve", paced)
    deps = SimpleNamespace(session_factory=factory, key_bytes=get_settings().key_bytes)
    with pytest.raises(DeferredError):
        await deliver_notice(job, deps)
    assert job.payload["delivered_recipients"] == [recipients[0].target]
    await deliver_notice(job, deps)
    assert client.send_text.await_count == 2
    assert [call.args[1] for call in client.send_text.await_args_list] == [
        recipient.target for recipient in recipients
    ]
