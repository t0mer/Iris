from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.alerts.quiet_hours import defer_if_quiet, quiet_until
from app.db.models import Job, Setting
from app.jobs import queue
from app.jobs.worker import run_one
from app.provider_health import PREFIX, deliver_notice
from app.settings_store import set_setting

QUIET = {"enabled": True, "start": "22:00", "end": "07:00"}


def test_overnight_boundaries_and_timezone():
    assert quiet_until(QUIET, "Asia/Jerusalem", datetime(2026, 10, 10, 18, 59, tzinfo=UTC)) is None
    assert quiet_until(QUIET, "Asia/Jerusalem", datetime(2026, 10, 10, 19, tzinfo=UTC)) == datetime(
        2026, 10, 11, 4, tzinfo=UTC
    )
    assert quiet_until(QUIET, "Asia/Jerusalem", datetime(2026, 10, 11, 4, tzinfo=UTC)) is None
    assert quiet_until({**QUIET, "enabled": False}, "UTC", datetime.now(UTC)) is None


def test_dst_repeated_end_waits_for_second_occurrence_and_skipped_end_moves_forward():
    config = {**QUIET, "end": "02:30"}
    assert quiet_until(
        config, "Europe/Berlin", datetime(2026, 10, 25, 0, 45, tzinfo=UTC)
    ) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert quiet_until(
        config, "Europe/Berlin", datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    ) == datetime(2026, 3, 29, 1, tzinfo=UTC)


async def test_quiet_wait_is_durable_preserves_checkpoint_and_does_not_use_retries(app_client):
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    start = (now - timedelta(hours=1)).strftime("%H:%M")
    end = (now + timedelta(hours=1)).strftime("%H:%M")
    async with factory() as db:
        await set_setting(db, "alerts.timezone", "UTC")
        await set_setting(
            db, "alerts.parent_quiet_hours", {"enabled": True, "start": start, "end": end}
        )
        jid = await queue.enqueue(
            db, "deliver_alert", {"delivered_recipients": ["done"]}, max_attempts=1
        )
        await db.commit()
    claimed = await queue.claim(factory)
    assert claimed and claimed.id == jid

    async def handler(job, deps):
        async with factory() as db:
            await defer_if_quiet(db, job, "parent")

    assert (
        await run_one(claimed, SimpleNamespace(session_factory=factory), {"deliver_alert": handler})
        == "queued"
    )
    async with factory() as db:
        row = await db.get(Job, jid)
        assert row.attempts == 0 and row.last_error == "Waiting for quiet hours"
        assert row.payload["delivered_recipients"] == ["done"]
        assert row.run_after > now + timedelta(minutes=30)
    # Disabling quiet hours wakes this existing job; it does not duplicate or discard it.
    response = await app_client.put(
        "/api/settings",
        json={"settings": {"alerts.parent_quiet_hours": {**QUIET, "enabled": False}}},
    )
    assert response.status_code == 200
    ready = await queue.claim(factory)
    assert ready and ready.id == jid


async def test_system_quiet_wait_precedes_hourly_reservation_and_stale_outage_is_skipped(
    app_client, monkeypatch
):
    factory = app_client.app.state.session_factory
    now = datetime.now(UTC)
    async with factory() as db:
        await set_setting(db, "alerts.timezone", "UTC")
        await set_setting(
            db,
            "alerts.system_quiet_hours",
            {
                "enabled": True,
                "start": (now - timedelta(hours=1)).strftime("%H:%M"),
                "end": (now + timedelta(hours=1)).strftime("%H:%M"),
            },
        )
        db.add(Setting(key=PREFIX + "openwa", value={"name": "OpenWA", "status": "down"}))
        jid = await queue.enqueue(
            db, "provider_notice", {"provider": "openwa", "status": "down"}, max_attempts=1
        )
        await db.commit()
    claimed = await queue.claim(factory)
    assert claimed is not None and claimed.id == jid
    with pytest.raises(queue.DeferredError):
        await deliver_notice(claimed, SimpleNamespace(session_factory=factory))
    async with factory() as db:
        health = await db.get(Setting, PREFIX + "openwa")
        assert "attempted_at" not in health.value
        health.value = {"name": "OpenWA", "status": "up"}
        await db.commit()
    build = AsyncMock()
    monkeypatch.setattr("app.provider_health.build_client", build)
    await deliver_notice(claimed, SimpleNamespace(session_factory=factory))
    build.assert_not_called()


@pytest.mark.parametrize(
    "value", [{**QUIET, "start": "25:00"}, {**QUIET, "end": "22:00"}, {**QUIET, "enabled": "true"}]
)
async def test_invalid_windows_rejected_atomically(app_client, value):
    response = await app_client.put(
        "/api/settings", json={"settings": {"alerts.parent_quiet_hours": value}}
    )
    assert response.status_code == 422
