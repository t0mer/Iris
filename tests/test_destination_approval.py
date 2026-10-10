import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import respx

from app.alerts.channels import build_client
from app.config import get_settings
from tests.test_alert_readiness import parent
from tests.test_alerts import setup

BOT = "123456:abcdefghijklmnopqrstuvwx"


@respx.mock
async def test_telegram_approval_is_one_use_bound_to_current_destination(app_client: Any) -> None:
    uid = await parent(app_client, "parent")
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "parent@example.com",
                "alerts.telegram_bot_token": BOT,
                "alerts.recipient_contacts": {"parent@example.com": {"telegram_chat_id": "1234"}},
            }
        },
    )
    blocked = await app_client.put(
        "/api/settings", json={"settings": {"alerts.channel": "telegram"}}
    )
    assert blocked.status_code == 200
    route = respx.post(f"https://api.telegram.org/bot{BOT}/sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 1}}
    )
    response = await app_client.post(
        f"/api/users/{uid}/approve-contact", json={"channel": "telegram"}
    )
    assert response.status_code == 200
    text = json.loads(route.calls.last.request.content)["text"]
    link = re.search(r"http[^\s]+", text).group()
    token = parse_qs(urlsplit(link).query)["token"][0]
    assert (await app_client.get("/api/settings/alert-readiness?channel=telegram")).json()["ready"]
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 200
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 400
    assert (
        await app_client.put("/api/settings", json={"settings": {"alerts.channel": "telegram"}})
    ).status_code == 200
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient_contacts": {"parent@example.com": {"telegram_chat_id": "5678"}}
            }
        },
    )
    assert (await app_client.get("/api/settings/alert-readiness")).json()["ready"]
    async with app_client.app.state.session_factory() as db:
        client = await build_client(db, None, get_settings().key_bytes, "telegram")
        await client.send_text("", "email:parent@example.com", "synthetic alert")
        await client.aclose()
    assert route.call_count == 2
    assert json.loads(route.calls.last.request.content)["chat_id"] == "5678"


@respx.mock
async def test_openwa_can_send_approval_without_greenapi(app_client: Any) -> None:
    deps, _, sender_id = await setup(app_client, recipient=None)
    await app_client.put(
        "/api/settings", json={"settings": {"alerts.sender_instance_id": sender_id}}
    )
    uid = await parent(app_client, "parent", "+15550100102")
    respx.get("https://wa.x/api/sessions/sender-sess").respond(200, json={"status": "ready"})
    send = respx.post("https://wa.x/api/sessions/sender-sess/messages/send-text").respond(
        201, json={"id": "synthetic"}
    )
    result = await app_client.post(
        f"/api/users/{uid}/approve-contact", json={"channel": "whatsapp"}
    )
    assert result.status_code == 200 and send.called
    users = (await app_client.get("/api/users")).json()
    assert not next(u for u in users if u["id"] == uid)["whatsapp_verified"]
    assert all("sendSeen" not in str(call.request.url) for call in respx.calls)
    await deps.providers.aclose()
