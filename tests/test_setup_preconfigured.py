import json
from typing import Any

from app.config import get_settings
from app.monitoring import states
from app.security.crypto import encrypt
from app.security.two_factor import GREEN_API_KEY, green_api_config, save
from app.setup_checks import notifier_test_passed, record_notifier_test
from tests.test_alert_readiness import parent, provider
from tests.test_instances import BODY


async def test_notification_test_expires_when_destination_changes(app_client: Any) -> None:
    async with app_client.app.state.session_factory() as db:
        await record_notifier_test(db, "telegram")
        await db.commit()
        assert await notifier_test_passed(db, "telegram")
    await app_client.put(
        "/api/settings", json={"settings": {"alerts.recipient": "parent@example.com"}}
    )
    async with app_client.app.state.session_factory() as db:
        assert not await notifier_test_passed(db, "telegram")


async def test_preconfigured_installation_does_not_interrupt_home(app_client: Any) -> None:
    iid = (await app_client.post("/api/instances", json=BODY)).json()["id"]
    await parent(app_client, "parent", "+15550100102", False)
    await provider(app_client, GREEN_API_KEY)
    async with app_client.app.state.session_factory() as db:
        config = await green_api_config(db, get_settings())
        config["delivery_verified"] = True
        await save(db, GREEN_API_KEY, encrypt(get_settings().key_bytes, json.dumps(config)), True)
        await db.commit()
    await app_client.put(
        "/api/settings",
        json={"settings": {"alerts.recipient": "+15550100102", "alerts.channel": "greenapi"}},
    )
    states[iid] = True
    state = (await app_client.get("/api/setup")).json()
    assert all(step["ready"] for step in state["steps"][:4])
    assert state["needs_setup"]  # AI is not considered tested just because credentials exist.
    states.clear()


async def test_telegram_setup_accepts_selected_parent_without_contact_approval(
    app_client: Any,
) -> None:
    await parent(app_client, "parent")
    result = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "telegram",
                "alerts.recipient": "parent@example.com",
                "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
                "alerts.recipient_contacts": {"parent@example.com": {"telegram_chat_id": "1234"}},
            }
        },
    )
    assert result.status_code == 200
    state = (await app_client.get("/api/setup")).json()
    assert next(step for step in state["steps"] if step["id"] == "parents")["ready"]
    readiness = (await app_client.get("/api/settings/alert-readiness")).json()
    assert readiness["ready"] and not readiness["issues"]
