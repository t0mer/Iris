import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import respx
from sqlalchemy import select

from app.alerts.actions import accept, buttons, decide, poll
from app.alerts.channels import ChannelClient
from app.db.models import Alert, AlertAction, Chat, Message, ReviewFeedback, ReviewResponse
from app.settings_store import set_setting

TARGET = "972501234567@c.us"
CONFIG = {"token": "123456:abcdefghijklmnopqrstuvwx"}


async def sample(c: Any) -> tuple[int, int]:
    async with c.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="test@g.us", name="School friends", is_group=True)
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id,
            wa_message_id="review",
            type="text",
            text="Hello",
            sent_at=datetime.now(UTC),
            verdict="review",
            status="done",
        )
        db.add(message)
        await db.flush()
        alert = Alert(
            message_id=message.id,
            categories=["violence"],
            max_score=0.4,
            kid_names=["Alex"],
            quote="Hello",
        )
        db.add(alert)
        await db.commit()
        await set_setting(db, "alerts.recipient", TARGET)
        await set_setting(db, "alerts.recipient_contacts", {TARGET: {"telegram_chat_id": "1001"}})
        await set_setting(db, "alerts.telegram_bot_token", CONFIG["token"], b"k" * 32)
        await set_setting(db, "alerts.review_buttons", True)
        return message.id, alert.id


async def test_concurrent_parent_choices_keep_first_and_notes(app_client: Any) -> None:
    mid, aid = await sample(app_client)
    factory = app_client.app.state.session_factory

    async def choose(choice: str, actor: str, event: str) -> Any:
        async with factory() as db:
            message = await db.get(Message, mid)
            assert message
            return await decide(db, message, choice, actor, event, factory)

    first, second = await asyncio.gather(
        choose("safe", "Parent A", "a"), choose("harmful", "Parent B", "b")
    )
    assert sum(r["applied"] for r in (first, second)) == 1
    winner = "safe" if first["applied"] else "harmful"
    async with factory() as db:
        assert (await db.get(Message, mid)).verdict == winner
        assert (await db.get(ReviewFeedback, mid)).verdict == winner
        assert (await db.get(Alert, aid)).status == (
            "dismissed" if winner == "safe" else "acknowledged"
        )
        notes = list(await db.scalars(select(ReviewResponse)))
        assert len(notes) == 2
        assert sum(n.applied for n in notes) == 1
        assert "Kept the first decision" in next(n.note for n in notes if not n.applied)
    history = (await app_client.get("/api/review?view=responses")).json()
    assert history["total"] == 1 and len(history["items"][0]["response_notes"]) == 2
    assert (await app_client.get("/api/review")).json()["total"] == 0
    assert len((await app_client.get(f"/api/alerts/{aid}")).json()["response_notes"]) == 2


async def test_buttons_validate_parent_expiry_config_and_replay(app_client: Any) -> None:
    mid, aid = await sample(app_client)
    factory = app_client.app.state.session_factory
    async with factory() as db:
        opts = await buttons(db, aid, TARGET, "telegram", "1001", CONFIG)
        assert len(opts) == 3 and all(len(o["id"].encode()) <= 64 for o in opts)
        token = next(o["id"] for o in opts if o["text"] == "SAFE")
        assert "another parent" in await accept(
            db, "telegram", CONFIG, token, "1001", "1002", "1", factory
        )
        assert "does not belong" in await accept(
            db, "telegram", {"token": "changed"}, token, "1001", "1001", "1", factory
        )
        assert "First response accepted" in await accept(
            db, "telegram", CONFIG, token, "1001", "1001", "1", factory
        )
        await accept(db, "telegram", CONFIG, token, "1001", "1001", "1", factory)
        assert len(list(await db.scalars(select(ReviewResponse)))) == 1
        action = await db.get(AlertAction, token)
        action.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        assert "expired" in await accept(
            db, "telegram", CONFIG, token, "1001", "1001", "2", factory
        )
        assert (await db.get(Message, mid)).verdict == "safe"


async def test_removed_recipient_and_group_buttons_are_rejected(app_client: Any) -> None:
    _, aid = await sample(app_client)
    factory = app_client.app.state.session_factory
    async with factory() as db:
        assert await buttons(db, aid, TARGET, "telegram", "-123", CONFIG) == []
        assert await buttons(db, aid, TARGET, "greenapi", "123@g.us", CONFIG) == []
        token = (await buttons(db, aid, TARGET, "telegram", "1001", CONFIG))[0]["id"]
        await set_setting(db, "alerts.recipient", "")
        assert "no longer eligible" in await accept(
            db, "telegram", CONFIG, token, "1001", "1001", "1", factory
        )


@respx.mock
async def test_telegram_poll_commits_response_and_offset(app_client: Any) -> None:
    mid, aid = await sample(app_client)
    factory = app_client.app.state.session_factory
    async with factory() as db:
        token = next(
            o["id"]
            for o in await buttons(db, aid, TARGET, "telegram", "1001", CONFIG)
            if o["text"] == "Ignore"
        )
    base = f"https://api.telegram.org/bot{CONFIG['token']}"
    respx.post(base + "/getWebhookInfo").respond(200, json={"ok": True, "result": {}})
    updates = respx.post(base + "/getUpdates").respond(
        200,
        json={
            "ok": True,
            "result": [
                {
                    "update_id": 4,
                    "callback_query": {
                        "id": "cb4",
                        "data": token,
                        "from": {"id": 1001},
                        "message": {"chat": {"id": 1001}},
                    },
                }
            ],
        },
    )
    respx.post(base + "/answerCallbackQuery").respond(200, json={"ok": True, "result": True})
    assert (await poll(factory))["responses_checked"] == 1
    await poll(factory)
    import json

    assert json.loads(updates.calls[1].request.content)["offset"] == 5
    async with factory() as db:
        assert (await db.get(Message, mid)).verdict == "ignored"
        assert len(list(await db.scalars(select(ReviewResponse)))) == 1


@respx.mock
async def test_transports_send_recipient_bound_buttons() -> None:
    import json

    telegram = ChannelClient(
        "telegram", None, CONFIG, {TARGET: {"telegram_chat_id": "1001"}}, b"k" * 32
    )
    telegram.buttons = [{"id": "iris:test", "text": "SAFE"}]
    route = respx.post(f"https://api.telegram.org/bot{CONFIG['token']}/sendMessage").respond(
        200, json={"ok": True}
    )
    await telegram.send_text("", TARGET, "Alert")
    assert (
        json.loads(route.calls[0].request.content)["reply_markup"]["inline_keyboard"][0][0][
            "callback_data"
        ]
        == "iris:test"
    )
    green = ChannelClient(
        "greenapi",
        None,
        {"api_url": "https://green.test", "instance_id": "1", "token": "secret"},
        {},
        b"k" * 32,
    )
    green.buttons = telegram.buttons
    route = respx.post("https://green.test/waInstance1/sendInteractiveButtonsReply/secret").respond(
        200, json={"idMessage": "msg"}
    )
    await green.send_text("", TARGET, "Alert")
    assert json.loads(route.calls[0].request.content)["buttons"][0]["buttonId"] == "iris:test"


@respx.mock
async def test_green_poll_acknowledges_after_commit_and_replay_is_a_noop(app_client: Any) -> None:
    import json

    from app.db.models import Setting
    from app.security.crypto import encrypt

    mid, aid = await sample(app_client)
    factory = app_client.app.state.session_factory
    config = {
        "api_url": "https://green.test",
        "instance_id": "1",
        "token": "secret",
        "verified": True,
    }
    async with factory() as db:
        db.add(Setting(key="security.green_api", value=encrypt(b"k" * 32, json.dumps(config))))
        await db.commit()
        token = next(
            o["id"]
            for o in await buttons(db, aid, TARGET, "greenapi", TARGET, config)
            if o["text"] == "SAFE"
        )
    base = "https://green.test/waInstance1"
    respx.get(base + "/getSettings/secret").respond(
        200, json={"incomingWebhook": "yes", "webhookUrl": ""}
    )
    notification = {
        "receiptId": 7,
        "body": {
            "typeWebhook": "incomingMessageReceived",
            "idMessage": "selection7",
            "senderData": {"chatId": TARGET, "sender": TARGET},
            "messageData": {
                "typeMessage": "templateButtonsReplyMessage",
                "templateButtonReplyMessage": {"selectedId": token},
            },
        },
    }
    respx.get(base + "/receiveNotification/secret").mock(
        side_effect=[
            httpx.Response(200, json=notification),
            httpx.Response(200, json=None),
            httpx.Response(200, json=notification),
            httpx.Response(200, json=None),
        ]
    )

    async def acknowledge(request: httpx.Request) -> httpx.Response:
        async with factory() as db:
            assert (await db.get(Message, mid)).verdict == "safe"
            assert len(list(await db.scalars(select(ReviewResponse)))) == 1
        return httpx.Response(200, json={"result": True})

    deletion = respx.delete(base + "/deleteNotification/secret/7").mock(side_effect=acknowledge)
    await poll(factory)
    await poll(factory)
    assert deletion.call_count == 2


@respx.mock
async def test_green_webhook_conflict_is_reported_without_polling_or_crashing(
    app_client: Any,
) -> None:
    import json

    from app.db.models import Setting
    from app.security.crypto import encrypt

    _, aid = await sample(app_client)
    factory = app_client.app.state.session_factory
    config = {
        "api_url": "https://green.test",
        "instance_id": "1",
        "token": "secret",
        "verified": True,
    }
    async with factory() as db:
        db.add(Setting(key="security.green_api", value=encrypt(b"k" * 32, json.dumps(config))))
        await db.commit()
        await buttons(db, aid, TARGET, "greenapi", TARGET, config)
    respx.get("https://green.test/waInstance1/getSettings/secret").respond(
        200, json={"incomingWebhook": "yes", "webhookUrl": "https://existing.example/webhook"}
    )
    result = await poll(factory)
    assert result["responses_checked"] == 0
    assert "webhook" in result["issues"][0]
    assert all("receiveNotification" not in str(call.request.url) for call in respx.calls)
    assert all(call.request.method == "GET" for call in respx.calls)
