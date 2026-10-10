from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Instance, Job, Message, Setting
from app.openwa.recovery import recover, stored_event
from tests.test_instances import BODY


def row(i: int = 1, **changes: Any) -> dict[str, Any]:
    return {
        "id": f"db-{i}",
        "sessionId": "sess-1",
        "waMessageId": f"false_972@g.us_hash{i}",
        "chatId": "972@g.us",
        "from": "sender@c.us",
        "author": "sender@c.us",
        "body": "שלום חברים",
        "type": "text",
        "direction": "incoming",
        "timestamp": int(datetime.now(UTC).timestamp()),
        "status": "delivered",
        "createdAt": datetime.now(UTC).isoformat(),
        "metadata": {},
        **changes,
    }


async def instance(client: Any) -> int:
    return (await client.post("/api/instances", json=BODY)).json()["id"]


def hooks(url: str) -> None:
    respx.get("https://wa.example.com/api/sessions/sess-1/webhooks").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "ours", "url": url, "retryCount": 3},
                {"id": "other", "url": "https://other/hook", "retryCount": 1},
            ],
        )
    )


@respx.mock
async def test_recovers_hebrew_once_and_updates_only_iris_webhook(app_client: Any):
    iid = await instance(app_client)
    inst = (await app_client.get(f"/api/instances/{iid}")).json()
    hooks(inst["webhook_url"])
    patch = respx.put("https://wa.example.com/api/sessions/sess-1/webhooks/ours").mock(
        return_value=httpx.Response(200, json={})
    )
    history = respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        return_value=httpx.Response(200, json={"messages": [row()], "total": 1})
    )
    assert (
        await app_client.put("/api/settings", json={"settings": {"openwa.webhook_attempts": 5}})
    ).status_code == 200
    factory = app_client.app.state.session_factory
    result = await recover(factory, get_settings().key_bytes)
    assert result["accepted"] == 1 and result["errors"] == []
    assert patch.calls.last.request.content == b'{"retryCount":5}'
    assert history.calls.last.request.url.params["inlineMedia"] == "false"
    result = await recover(factory, get_settings().key_bytes)
    assert result["duplicate"] == 1
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Message)) == 1
        assert (
            await db.scalar(
                select(func.count()).select_from(Job).where(Job.type == "process_message")
            )
            == 1
        )
        assert (await db.scalar(select(Message))).text == "שלום חברים"


@respx.mock
async def test_scope_wrong_session_failed_send_and_old_messages_are_not_imported(app_client: Any):
    iid = await instance(app_client)
    hooks((await app_client.get(f"/api/instances/{iid}")).json()["webhook_url"])
    rows = [
        row(1, sessionId="another"),
        row(2, direction="outgoing", status="failed"),
        row(3, timestamp=int((datetime.now(UTC) - timedelta(days=10)).timestamp())),
        row(4),
    ]
    respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        return_value=httpx.Response(200, json={"messages": rows})
    )
    await app_client.put("/api/settings", json={"settings": {"scope.monitor_groups": False}})
    result = await recover(app_client.app.state.session_factory, get_settings().key_bytes)
    assert result["accepted"] == 0 and result["invalid"] == 1 and result["skipped"] == 3


@respx.mock
@pytest.mark.parametrize("manual", [False, True])
async def test_disabled_recovery_allows_only_explicit_manual_pull(app_client: Any, manual: bool):
    iid = await instance(app_client)
    hooks((await app_client.get(f"/api/instances/{iid}")).json()["webhook_url"])
    history = respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        return_value=httpx.Response(200, json={"messages": []})
    )
    await app_client.put("/api/settings", json={"settings": {"openwa.recovery_enabled": False}})
    await recover(app_client.app.state.session_factory, get_settings().key_bytes, manual=manual)
    assert history.called == manual


@respx.mock
async def test_paused_phone_does_not_access_openwa(app_client: Any):
    iid = await instance(app_client)
    factory = app_client.app.state.session_factory
    async with factory() as db:
        inst = await db.get(Instance, iid)
        inst.enabled = False
        await db.commit()
    assert (await recover(factory, get_settings().key_bytes))["pages"] == 0


@respx.mock
async def test_resume_keyset_cursor_and_do_not_advance_on_upstream_failure(
    app_client: Any, monkeypatch: Any
):
    iid = await instance(app_client)
    hooks((await app_client.get(f"/api/instances/{iid}")).json()["webhook_url"])
    captured: list[str] = []

    async def store(_db: Any, _iid: int, _name: str, message: Any) -> str:
        captured.append(message.wa_message_id)
        return "accepted"

    monkeypatch.setattr("app.openwa.recovery._store", store)
    created = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()

    def page(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        start = int(after.split("-")[1]) + 1 if after else 0
        return httpx.Response(
            200,
            json={
                "messages": [row(i, createdAt=created) for i in range(start, min(start + 100, 301))]
            },
        )

    history = respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        side_effect=page
    )
    factory = app_client.app.state.session_factory
    assert (await recover(factory, get_settings().key_bytes))["accepted"] == 300
    async with factory() as db:
        before = dict((await db.get(Setting, f"internal.openwa_recovery.{iid}")).value)
    history.mock(return_value=httpx.Response(503, json={"message": "secret upstream payload"}))
    result = await recover(factory, get_settings().key_bytes)
    assert result["errors"][0]["status"] == 503 and "secret" not in str(result)
    async with factory() as db:
        assert (await db.get(Setting, f"internal.openwa_recovery.{iid}")).value == before
    history.mock(side_effect=page)
    assert (await recover(factory, get_settings().key_bytes))["accepted"] == 1
    assert len(set(captured)) == 301


def test_recovery_media_uses_original_metadata_without_base64_copy():
    data = stored_event(row(type="image", mediaMimetype="image/jpeg"), "sess-1")["data"]
    assert data["media"] == {"mimetype": "image/jpeg", "omitted": True}


@respx.mock
async def test_recovery_duplicate_never_restores_withheld_media(app_client: Any):
    from app.alerts.service import redact_message

    iid = await instance(app_client)
    hooks((await app_client.get(f"/api/instances/{iid}")).json()["webhook_url"])
    respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        return_value=httpx.Response(
            200, json={"messages": [row(type="image", mediaMimetype="image/jpeg")]}
        )
    )
    factory = app_client.app.state.session_factory
    await recover(factory, get_settings().key_bytes)
    async with factory() as db:
        message = await db.scalar(select(Message))
        redact_message(message)
        await db.commit()
    assert (await recover(factory, get_settings().key_bytes))["duplicate"] == 1
    async with factory() as db:
        message = await db.scalar(select(Message))
        assert message.redacted and message.media is None


@respx.mock
async def test_increasing_lookback_revisits_older_retained_messages(app_client: Any):
    iid = await instance(app_client)
    hooks((await app_client.get(f"/api/instances/{iid}")).json()["webhook_url"])
    older = datetime.now(UTC) - timedelta(hours=30)
    respx.get("https://wa.example.com/api/sessions/sess-1/messages").mock(
        return_value=httpx.Response(
            200,
            json={"messages": [row(createdAt=older.isoformat(), timestamp=int(older.timestamp()))]},
        )
    )
    factory = app_client.app.state.session_factory
    assert (await recover(factory, get_settings().key_bytes))["accepted"] == 0
    await app_client.put("/api/settings", json={"settings": {"openwa.recovery_hours": 48}})
    assert (await recover(factory, get_settings().key_bytes))["accepted"] == 1


async def test_retry_settings_validation(app_client: Any):
    for value in (0, 6, True, 2.5):
        assert (
            await app_client.put(
                "/api/settings", json={"settings": {"openwa.webhook_attempts": value}}
            )
        ).status_code == 422


def test_stored_poll_metadata_survives_catch_up():
    from app.openwa.payloads import parse_event

    event = stored_event(
        row(
            type="poll",
            metadata={
                "poll": {"question": "שאלה", "options": ["כן", "לא"], "allowMultipleAnswers": False}
            },
        ),
        "sess-1",
    )
    incoming = parse_event(event)
    assert incoming and incoming.type == "poll"
    assert incoming.text == "שאלה\n• כן\n• לא\nMultiple answers: no"
