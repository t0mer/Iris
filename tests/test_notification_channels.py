"""Notification transports never contact real providers in these regressions."""

import json
from unittest.mock import Mock

import httpx
import pytest
import respx

from app.alerts.channels import ChannelClient
from app.classify.moderation import URL as MOD_URL
from app.openwa.client import OpenWAError
from tests.test_alerts import run_all, setup
from tests.test_parent_recipients import advance_queue
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


@respx.mock
async def test_telegram_alert_uses_parent_destination_and_checkpoints(app_client):
    deps, token, _ = await setup(app_client, recipient="15550100101")
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "telegram",
                "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
                "alerts.recipient_contacts": {"15550100101": {"telegram_chat_id": "1234"}},
            }
        },
    )
    assert response.status_code == 200
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(
        "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwx/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert send.call_count == 1
    assert json.loads(send.calls[0].request.content)["chat_id"] == "1234"
    assert "Noa" in json.loads(send.calls[0].request.content)["text"]
    assert (await app_client.get("/api/stats")).json()["delivery_configured"]
    await deps.providers.aclose()


@respx.mock
async def test_greenapi_supports_group_destinations():
    client = ChannelClient(
        "greenapi",
        None,
        {"api_url": "https://api.green-api.com", "instance_id": "123", "token": "testtoken"},
        {},
        b"k" * 32,
    )
    route = respx.post("https://api.green-api.com/waInstance123/sendMessage/testtoken").mock(
        return_value=httpx.Response(200, json={"idMessage": "sent"})
    )
    await client.send_text("", "12345@g.us", "private summary")
    assert json.loads(route.calls[0].request.content) == {
        "chatId": "12345@g.us",
        "message": "private summary",
    }


async def test_smtp_alert_is_email_not_an_otp(monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.alerts.channels.send_email", send)
    client = ChannelClient(
        "smtp",
        None,
        {"verified": True},
        {"15550100101@c.us": {"email": "parent@example.com"}},
        b"k" * 32,
    )
    await client.send_text("", "15550100101@c.us", "alert summary")
    assert send.call_args.args[1:] == ("parent@example.com", "alert summary")


@respx.mock
async def test_uncertain_telegram_delivery_does_not_retry(app_client):
    deps, token, _ = await setup(app_client, recipient="15550100101")
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "telegram",
                "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
                "alerts.recipient_contacts": {"15550100101": {"telegram_chat_id": "1234"}},
            }
        },
    )
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    route = respx.post(
        "https://api.telegram.org/bot123456:abcdefghijklmnopqrstuvwx/sendMessage"
    ).mock(side_effect=httpx.ReadTimeout("timeout"))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    await advance_queue(deps)
    await run_all(deps)
    assert route.call_count == 1
    value = (await app_client.get("/api/alerts")).json()["items"][0]
    assert value["delivery_status"] == "failed" and "uncertain" in value["delivery_error"]
    await deps.providers.aclose()


async def test_missing_email_cannot_silently_send_elsewhere():
    client = ChannelClient("smtp", None, {}, {}, b"k" * 32)
    with pytest.raises(OpenWAError, match="email is missing"):
        await client.send_text("", "15550100101@c.us", "text")


async def test_environment_bootstrap_keeps_portal_preferences(app_client, monkeypatch):
    from app.alerts.bootstrap import bootstrap_notifications
    from app.config import get_settings
    from app.settings_store import get_secret, get_setting, set_setting

    cfg = get_settings()
    monkeypatch.setattr(cfg, "alert_channel", "telegram")
    monkeypatch.setattr(cfg, "telegram_bot_token", "123456:abcdefghijklmnopqrstuvwx")
    monkeypatch.setattr(cfg, "alert_recipients", "15550100101")
    monkeypatch.setattr(cfg, "telegram_chat_id", "1234")
    async with app_client.app.state.session_factory() as db:
        await set_setting(db, "alerts.channel", "smtp")
        await bootstrap_notifications(db, cfg)
        assert await get_setting(db, "alerts.channel") == "smtp"
        assert (
            await get_secret(db, "alerts.telegram_bot_token", cfg.key_bytes)
            == cfg.telegram_bot_token
        )
        assert (await get_setting(db, "alerts.recipient_contacts"))["15550100101@c.us"][
            "telegram_chat_id"
        ] == "1234"
