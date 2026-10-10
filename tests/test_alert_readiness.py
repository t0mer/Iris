"""Channel selection, optional contacts and send-time approval share one policy."""

import json
from typing import Any

import httpx
import pytest
import respx

from app.alerts.channels import build_client
from app.config import get_settings
from app.db.models import User
from app.security.crypto import encrypt
from app.security.two_factor import CONFIG_KEY, GREEN_API_KEY, save
from app.settings_store import get_setting
from tests.test_alerts import MOD_URL, SEND_URL, alerts, mod_response, run_all, setup
from tests.test_webhooks import fx, post


async def parent(c: Any, name: str, number: str | None = None, approved: bool = False) -> int:
    result = await c.post(
        "/api/users",
        json={
            "username": name,
            "role": "parent",
            "password": "strong-password",
            "email": f"{name}@example.com",
            "whatsapp_number": number,
        },
    )
    assert result.status_code == 201, result.text
    uid = result.json()["id"]
    async with c.app.state.session_factory() as db:
        user = await db.get(User, uid)
        user.whatsapp_verified = approved
        user.email_verified = True
        await db.commit()
    return uid


async def provider(c: Any, key: str) -> None:
    cfg = get_settings()
    config = (
        {
            "verified": True,
            "api_url": "https://api.green-api.com",
            "instance_id": "123",
            "token": "testtoken",
            "sender_number": "+15559999999",
        }
        if key == GREEN_API_KEY
        else {"verified": True}
    )
    async with c.app.state.session_factory() as db:
        await save(db, key, encrypt(cfg.key_bytes, json.dumps(config)), True)
        await db.commit()


async def test_verified_greenapi_sender_does_not_require_personal_approval_or_identity_cache(
    app_client: Any,
) -> None:
    await parent(app_client, "approved-parent", "+15550100102", approved=True)
    await provider(app_client, GREEN_API_KEY)
    async with app_client.app.state.session_factory() as db:
        await save(
            db,
            GREEN_API_KEY,
            encrypt(get_settings().key_bytes, json.dumps({"verified": True})),
            True,
        )
        await db.commit()
    await app_client.put("/api/settings", json={"settings": {"alerts.recipient": "+15550100102"}})
    status = (await app_client.get("/api/settings/alert-readiness?channel=greenapi")).json()
    assert status["provider_ready"] and status["ready"]
    assert status["provider_error"] is None


@respx.mock
async def test_greenapi_requires_verified_connection_without_phone_approval(
    app_client: Any,
) -> None:
    c = app_client
    await parent(c, "unapproved", "+15550100102")
    await parent(c, "missing")
    await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "missing@example.com, +15550100102",
            }
        },
    )
    result = await c.put("/api/settings", json={"settings": {"alerts.channel": "greenapi"}})
    assert result.status_code == 422 and "successfully test GreenAPI" in result.text
    await provider(c, GREEN_API_KEY)
    result = await c.put("/api/settings", json={"settings": {"alerts.channel": "greenapi"}})
    assert result.status_code == 200
    async with c.app.state.session_factory() as db:
        user = await db.get(User, 2)
        user.whatsapp_verified = True
        await db.commit()
    result = await c.put("/api/settings", json={"settings": {"alerts.channel": "greenapi"}})
    assert result.status_code == 200, result.text
    status = (await c.get("/api/settings/alert-readiness")).json()
    assert status["ready"] and status["eligible_count"] == 1 and status["invalid_count"] == 1
    assert all("approved" not in (r["reason"] or "") for r in status["recipients"])
    assert "No WhatsApp number" in next(
        r["reason"] for r in status["recipients"] if not r["eligible"]
    )
    send = respx.post("https://api.green-api.com/waInstance123/sendMessage/testtoken").respond(
        200, json={"idMessage": "ok"}
    )
    async with c.app.state.session_factory() as db:
        client = await build_client(db, None, get_settings().key_bytes, "greenapi")
        await client.send_text("", "15550100102@c.us", "test")
        await client.aclose()
    assert send.called


@pytest.mark.parametrize("channel", ["openwa"])
async def test_optional_number_missing_or_unapproved_rejects_channel(
    app_client: Any, channel: str
) -> None:
    c = app_client
    deps, _, _ = await setup(c, recipient=None)
    await parent(c, "missing")
    await parent(c, "unapproved", "+15550100102")
    if channel == "greenapi":
        await provider(c, GREEN_API_KEY)
    await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "missing@example.com, +15550100102",
            }
        },
    )
    result = await c.put("/api/settings", json={"settings": {"alerts.channel": channel}})
    assert result.status_code == 422
    assert "No WhatsApp number" in result.text and "not approved" in result.text
    status = (await c.get(f"/api/settings/alert-readiness?channel={channel}")).json()
    assert not status["ready"] and status["invalid_count"] == 2
    assert (await c.get("/api/stats")).json()["invalid_alert_recipients"] == 2
    await deps.providers.aclose()


async def test_empty_selected_list_cannot_select_channel_even_with_optional_accounts(
    app_client: Any,
) -> None:
    c = app_client
    await parent(c, "no_number")
    await c.put(
        "/api/settings",
        json={"settings": {"alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx"}},
    )
    for channel in ("openwa", "greenapi", "telegram", "smtp"):
        result = await c.put("/api/settings", json={"settings": {"alerts.channel": channel}})
        assert result.status_code == 422 and "No eligible recipients" in result.text
    status = (await c.get("/api/settings/alert-readiness")).json()
    assert any(u["username"] == "no_number" and not u["eligible"] for u in status["users"])


@respx.mock
async def test_one_approved_parent_allows_channel_other_users_marked_and_not_sent(
    app_client: Any,
) -> None:
    c = app_client
    deps, token, sender_id = await setup(c, recipient=None)
    await parent(c, "ready", "+15550100101", True)
    await parent(c, "not_ready", "+15550100102")
    await parent(c, "no_number")
    result = await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "openwa",
                "alerts.sender_instance_id": sender_id,
                "alerts.recipient": (
                    "ready@example.com, not_ready@example.com, no_number@example.com"
                ),
            }
        },
    )
    assert result.status_code == 200, result.text
    status = (await c.get("/api/settings/alert-readiness")).json()
    assert status["ready"] and status["eligible_count"] == 1 and status["invalid_count"] == 2
    stats = (await c.get("/api/stats")).json()
    assert stats["delivery_configured"] and stats["alert_delivery_issues"]
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    await post(c, token, fx("text_received_mixed"))
    await run_all(deps)
    assert send.call_count == 1
    assert json.loads(send.calls[0].request.content)["chatId"] == "15550100101@c.us"
    alert = (await alerts(c))[0]
    assert alert.delivery_status == "partial"
    assert "not approved" in alert.delivery_error and "No WhatsApp number" in alert.delivery_error
    await deps.providers.aclose()


async def test_return_to_whatsapp_rechecks_approval_and_keeps_last_channel_on_error(
    app_client: Any,
) -> None:
    c = app_client
    deps, _, _ = await setup(c, recipient=None)
    uid = await parent(c, "parent", "+15550100101", True)
    selected = "parent@example.com"
    async with c.app.state.session_factory() as db:
        await save(db, f"security.telegram_approved.{uid}", {"chat_id": "1234"})
        await db.commit()
    assert (
        await c.put(
            "/api/settings",
            json={
                "settings": {
                    "alerts.channel": "telegram",
                    "alerts.recipient": selected,
                    "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
                    "alerts.recipient_contacts": {selected: {"telegram_chat_id": "1234"}},
                }
            },
        )
    ).status_code == 200
    async with c.app.state.session_factory() as db:
        user = await db.get(User, uid)
        user.whatsapp_verified = False
        await db.commit()
    result = await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "openwa",
                "alerts.cooldown_minutes": 77,
            }
        },
    )
    assert result.status_code == 422 and "not approved" in result.text
    async with c.app.state.session_factory() as db:
        assert await get_setting(db, "alerts.channel") == "telegram"
        assert await get_setting(db, "alerts.cooldown_minutes") != 77
    await deps.providers.aclose()


async def test_selected_account_number_change_never_falls_back_to_legacy(app_client: Any) -> None:
    c = app_client
    deps, _, _ = await setup(c, recipient=None)
    uid = await parent(c, "parent", "+15550100101", True)
    await c.put("/api/settings", json={"settings": {"alerts.recipient": "+15550100101"}})
    changed = await c.put(
        f"/api/users/{uid}",
        json={
            "username": "parent",
            "whatsapp_number": "+15550100103",
        },
    )
    assert changed.status_code == 200
    status = (await c.get("/api/settings/alert-readiness")).json()
    recipient = status["recipients"][0]
    assert recipient["user_id"] == uid and not recipient["legacy"]
    assert not recipient["eligible"] and "not approved" in recipient["reason"]
    assert not (await c.get("/api/stats")).json()["delivery_configured"]
    async with c.app.state.session_factory() as db:
        user = await db.get(User, uid)
        user.whatsapp_verified = True
        await db.commit()
    assert (await c.get("/api/settings/alert-readiness")).json()["recipients"][0][
        "destination"
    ] == "15550100103@c.us"
    await deps.providers.aclose()


async def test_legacy_destinations_still_work_and_users_are_not_auto_selected(
    app_client: Any,
) -> None:
    c = app_client
    deps, _, _ = await setup(c, recipient="15550100101")
    await parent(c, "unselected", "+15550100102", True)
    result = await c.put("/api/settings", json={"settings": {"alerts.channel": "openwa"}})
    assert result.status_code == 200
    status = (await c.get("/api/settings/alert-readiness")).json()
    assert len(status["recipients"]) == 1 and status["recipients"][0]["legacy"]
    assert next(u for u in status["users"] if u["username"] == "unselected")["selected"] is False
    await deps.providers.aclose()


async def test_telegram_requires_chat_id_but_phone_is_optional(app_client: Any) -> None:
    c = app_client
    uid = await parent(c, "parent")
    await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "parent@example.com",
                "alerts.telegram_bot_token": "123456:abcdefghijklmnopqrstuvwx",
            }
        },
    )
    blocked = await c.put("/api/settings", json={"settings": {"alerts.channel": "telegram"}})
    assert blocked.status_code == 422 and "No Telegram chat ID" in blocked.text
    valid = await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.channel": "telegram",
                "alerts.recipient_contacts": {"parent@example.com": {"telegram_chat_id": "1234"}},
            }
        },
    )
    assert valid.status_code == 200
    async with c.app.state.session_factory() as db:
        await save(db, f"security.telegram_approved.{uid}", {"chat_id": "1234"})
        await db.commit()
    assert (
        await c.put(
            "/api/settings",
            json={
                "settings": {
                    "alerts.channel": "telegram",
                    "alerts.recipient_contacts": {
                        "parent@example.com": {"telegram_chat_id": "1234"}
                    },
                }
            },
        )
    ).status_code == 200


async def test_smtp_user_approval_and_provider_both_required(app_client: Any) -> None:
    c = app_client
    uid = await parent(c, "parent")
    await c.put("/api/settings", json={"settings": {"alerts.recipient": "parent@example.com"}})
    assert (
        await c.put("/api/settings", json={"settings": {"alerts.channel": "smtp"}})
    ).status_code == 422
    await provider(c, CONFIG_KEY)
    # Old destination overrides must not replace a registered parent's profile email.
    override = await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient_contacts": {
                    "parent@example.com": {"email": "obsolete@example.com"}
                }
            }
        },
    )
    assert override.status_code == 200
    assert (
        await c.put("/api/settings", json={"settings": {"alerts.channel": "smtp"}})
    ).status_code == 200
    async with c.app.state.session_factory() as db:
        user = await db.get(User, uid)
        user.email_verified = False
        await db.commit()
    assert not (await c.get("/api/stats")).json()["delivery_configured"]


@respx.mock
async def test_approval_rechecked_at_send_not_only_settings_save(app_client: Any) -> None:
    c = app_client
    deps, _, sender_id = await setup(c, recipient=None)
    uid = await parent(c, "parent", "+15550100101", True)
    await c.put("/api/settings", json={"settings": {"alerts.recipient": "+15550100101"}})
    async with c.app.state.session_factory() as db:
        user = await db.get(User, uid)
        user.whatsapp_verified = False
        await db.commit()
        from app.db.models import Instance

        client = await build_client(db, await db.get(Instance, sender_id), get_settings().key_bytes)
        from app.openwa.client import OpenWAError

        with pytest.raises(OpenWAError, match="not approved"):
            await client.send_text("", "15550100101@c.us", "test")
        await client.aclose()
    assert not respx.calls
    await deps.providers.aclose()
