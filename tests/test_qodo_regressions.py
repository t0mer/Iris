"""Regression coverage for PR review findings, using synthetic content only."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import URL
from app.db.models import Chat, Job, Message
from app.jobs import handlers, queue
from app.media import ffmpeg
from tests.test_media_pipeline import MEDIA_URL, run_all, setup, the_message
from tests.test_worker import mod_response


@respx.mock
@pytest.mark.parametrize("kind", ["other", "poll"])
@pytest.mark.parametrize("caption", ["", "Classroom information"])
async def test_unreadable_content_remains_review_in_cloud_mode(app_client, kind, caption):
    deps, _ = await setup(app_client)
    respx.get(url__regex=MEDIA_URL).respond(200, content=b"opaque\x00unsupported")
    respx.post(URL).mock(return_value=mod_response())
    async with deps.session_factory() as db:
        chat = Chat(wa_chat_id="synthetic")
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id,
            wa_message_id="synthetic",
            type=kind,
            text=caption,
            sent_at=datetime.now(UTC),
            status="pending",
            media={"instance_id": 1, "message_ref": "synthetic", "chat_id": "synthetic"}
            if kind == "other"
            else None,
        )
        db.add(message)
        await db.flush()
        await queue.enqueue(db, "process_message", {"message_id": message.id})
    await run_all(deps)
    message, _ = await the_message(app_client)
    assert message.status == "done" and message.verdict == "review"
    assert message.review_reason
    await deps.providers.aclose()


@pytest.mark.parametrize("local", [False, True])
@respx.mock
async def test_ogg_attachment_video_never_has_audio_only_coverage(
    app_client, tmp_path, monkeypatch, local
):
    from tests.test_local_safety import enable

    if local:
        enable(monkeypatch, local=True)
    deps, _ = await setup(app_client)
    path = tmp_path / "video.ogv"
    await ffmpeg._run(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=32x32:rate=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440",
        "-t",
        "1",
        "-c:v",
        "libtheora",
        "-c:a",
        "libvorbis",
        str(path),
    )
    assert (await ffmpeg.probe(path)).has_video
    respx.get(url__regex=MEDIA_URL).respond(200, content=path.read_bytes())
    visual = AsyncMock(return_value=handlers.Prepared(image=["synthetic-frame"]))
    monkeypatch.setattr(handlers, "_video_prepare", visual)
    monkeypatch.setattr(handlers, "_transcribe", AsyncMock())
    async with deps.session_factory() as db:
        message = Message(
            type="document", media={"instance_id": 1, "message_ref": "ogg", "chat_id": "synthetic"}
        )
        result = await handlers._prepare(
            db, queue.ClaimedJob(991, "process_message", {}, 1, 3), deps, message
        )
    if local:
        visual.assert_awaited_once()
        assert result.image
    else:
        visual.assert_not_awaited()
        assert result.problem and "visuals" in str(result.problem)
    assert not result.media_analysis or result.media_analysis.get("method") != "attachment_audio_v1"
    await deps.providers.aclose()


async def test_combined_telegram_system_settings_use_pending_token(app_client):
    from app.config import get_settings
    from app.settings_store import get_secret, get_setting

    token = "123456:synthetic-telegram-bot-token"
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.provider_notification_channel": "telegram",
                "alerts.telegram_bot_token": token,
            }
        },
    )
    assert response.status_code == 200, response.text
    async with app_client.app.state.session_factory() as db:
        assert await get_setting(db, "alerts.provider_notification_channel") == "telegram"
        assert await get_secret(db, "alerts.telegram_bot_token", get_settings().key_bytes) == token
    rejected = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.provider_notification_channel": "telegram",
                "alerts.telegram_bot_token": "",
            }
        },
    )
    assert rejected.status_code == 422
    async with app_client.app.state.session_factory() as db:
        assert await get_secret(db, "alerts.telegram_bot_token", get_settings().key_bytes) == token


async def test_concurrent_manual_summaries_reserve_one_job(app_client):
    responses = await asyncio.gather(
        *(app_client.post("/api/schedules/daily_summary/run") for _ in range(6))
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409, 409, 409]
    async with app_client.app.state.session_factory() as db:
        jobs = list(await db.scalars(select(Job).where(Job.type == "run_schedule")))
        assert len(jobs) == 1
        job_id = jobs[0].id
    await queue.ack(app_client.app.state.session_factory, job_id)
    assert (await app_client.post("/api/schedules/daily_summary/run")).status_code == 200


async def test_manual_and_automatic_summary_share_reservation(app_client):
    from types import SimpleNamespace

    from app.schedules import due_schedules

    deps = SimpleNamespace(session_factory=app_client.app.state.session_factory)
    response, _ = await asyncio.gather(
        app_client.post("/api/schedules/daily_summary/run"),
        due_schedules(deps, datetime(2026, 10, 15, 21, tzinfo=UTC)),
    )
    assert response.status_code in (200, 409)
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


@respx.mock
async def test_audio_cover_art_is_checked_without_video_duration_limit(
    app_client, tmp_path, monkeypatch
):
    deps, _ = await setup(app_client)
    cover = tmp_path / "cover.jpg"
    await ffmpeg._run(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=size=32x32",
        "-frames:v",
        "1",
        str(cover),
    )
    path = tmp_path / "cover.mp3"
    await ffmpeg._run(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=61",
        "-i",
        str(cover),
        "-map",
        "0:a",
        "-map",
        "1:v",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "32k",
        "-c:v",
        "copy",
        "-disposition:v",
        "attached_pic",
        str(path),
    )
    info = await ffmpeg.probe(path)
    assert info.has_audio and not info.has_video and info.cover_art_count == 1
    assert info.duration > 60
    respx.get(url__regex=MEDIA_URL).respond(200, content=path.read_bytes())
    transcribe = AsyncMock()
    visual = AsyncMock()
    monkeypatch.setattr(handlers, "_transcribe", transcribe)
    monkeypatch.setattr(handlers, "_video_prepare", visual)
    async with deps.session_factory() as db:
        message = Message(
            type="document",
            media={"instance_id": 1, "message_ref": "audio", "chat_id": "synthetic"},
        )
        result = await handlers._prepare(
            db, queue.ClaimedJob(992, "process_message", {}, 1, 3), deps, message
        )
    assert result.problem is None
    assert result.image.startswith("data:image/jpeg;base64,")
    assert result.media_analysis == {"method": "attachment_audio_v1", "complete": True}
    transcribe.assert_awaited_once()
    visual.assert_not_awaited()
    await deps.providers.aclose()


@respx.mock
@pytest.mark.parametrize("concurrent", [False, True])
async def test_manual_and_automatic_connection_alerts_share_incident(
    app_client, monkeypatch, concurrent
):
    from app.db.models import Instance, Setting
    from app.monitoring import session_details
    from app.schedules import check_connections
    from app.settings_store import set_setting
    from tests.test_alerts import setup as alert_setup

    deps, _, sender_id = await alert_setup(app_client)
    now = datetime.now(UTC)
    async with deps.session_factory() as db:
        child = await db.scalar(select(Instance).where(Instance.id != sender_id))
        child_id = child.id
        await set_setting(
            db, "schedules.config", {"connections": {"retry_count": 0, "notify_wait_minutes": 1}}
        )
        db.add(
            Setting(
                key=f"internal.monitoring_health.{child_id}",
                value={
                    "issues": ["WhatsApp connection is disconnected"],
                    "connection_status": "disconnected",
                    "incident": 1,
                },
            )
        )
        db.add(
            Setting(
                key=f"internal.connection_recovery.{child_id}",
                value={"offline_since": now.timestamp() - 600, "attempts": 0},
            )
        )
        await db.commit()

    async def probe(instance, key):
        session_details[instance.id] = ("disconnected" if instance.id == child_id else "ready", now)

    monkeypatch.setattr("app.monitoring.probe_instance", probe)
    if concurrent:
        response, _ = await asyncio.gather(
            app_client.post("/api/schedules/connection_notifications/run"),
            check_connections(deps, now),
        )
        assert response.status_code in (200, 409)
    else:
        assert (
            await app_client.post("/api/schedules/connection_notifications/run")
        ).status_code == 200
        await check_connections(deps, now)
    await check_connections(deps, now)
    async with deps.session_factory() as db:
        jobs = list(await db.scalars(select(Job).where(Job.type == "run_schedule")))
        assert len(jobs) == 1
        assert jobs[0].payload["incident"] == 1
        assert (await db.get(Setting, f"internal.connection_recovery.{child_id}")).value["notified"]
    await deps.providers.aclose()
