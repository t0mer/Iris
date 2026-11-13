"""Per-parent transports must agree across settings, health, delivery and retries."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from sqlalchemy import select

from app.db.models import Job, User
from app.security.two_factor import CONFIG_KEY, GREEN_API_KEY
from tests.test_alert_readiness import parent, provider
from tests.test_alerts import MOD_URL, alerts, mod_response, run_all, setup
from tests.test_webhooks import fx, post


async def mixed_parents(c: Any) -> dict[str, str]:
    await parent(c, "whatsapp-parent", "+15550100101")
    await parent(c, "mail-parent")
    await provider(c, GREEN_API_KEY)
    await provider(c, CONFIG_KEY)
    mapping = {
        "email:whatsapp-parent@example.com": "greenapi",
        "email:mail-parent@example.com": "smtp",
    }
    result = await c.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": ", ".join(mapping),
                "alerts.recipient_channels": mapping,
            }
        },
    )
    assert result.status_code == 200, result.text
    return mapping


async def test_recipient_channels_are_persisted_and_resolve_actual_destinations(
    app_client: Any,
) -> None:
    mapping = await mixed_parents(app_client)
    result = (await app_client.get("/api/settings/alert-readiness")).json()
    assert result["ready"] and result["eligible_count"] == 2
    rows = {r["target"]: r for r in result["recipients"]}
    for target, channel in mapping.items():
        assert rows[target]["channel"] == channel
    assert rows["email:whatsapp-parent@example.com"]["destination"] == "15550100101@c.us"
    assert rows["email:mail-parent@example.com"]["destination"] == "mail-parent@example.com"
    green = (await app_client.get("/api/settings/alert-readiness?channel=greenapi")).json()
    assert [r["target"] for r in green["recipients"]] == ["email:whatsapp-parent@example.com"]


async def test_channel_options_hide_unconfigured_providers_and_validate_each_parent(
    app_client: Any,
) -> None:
    await parent(app_client, "mail-only")
    result = (await app_client.get("/api/settings/recipient-channels")).json()
    assert not any(option["configured"] for option in result["channels"])
    await provider(app_client, GREEN_API_KEY)
    result = (await app_client.get("/api/settings/recipient-channels")).json()
    green = next(option for option in result["channels"] if option["channel"] == "greenapi")
    assert green["configured"]
    row = next(r for r in green["recipients"] if r["name"] == "mail-only")
    assert not row["eligible"] and "No WhatsApp number" in row["reason"]
    result = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "mail-only@example.com",
                "alerts.recipient_channels": {"email:mail-only@example.com": "greenapi"},
            }
        },
    )
    assert result.status_code == 422 and "No WhatsApp number" in result.text
    result = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.recipient": "mail-only@example.com",
                "alerts.recipient_channels": {"email:mail-only@example.com": "smtp"},
            }
        },
    )
    assert result.status_code == 422 and "test SMTP" in result.text
    assert (await app_client.get("/api/settings")).json()["alerts.recipient"] is None


@respx.mock
async def test_mixed_delivery_and_retry_do_not_repeat_completed_parents(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    try:
        monkeypatch.setattr("app.alerts.delivery.reserve", AsyncMock())
        await mixed_parents(app_client)
        respx.post(MOD_URL).mock(return_value=mod_response(harassment=0.9))
        green = respx.post("https://api.green-api.com/waInstance123/sendMessage/testtoken").mock(
            side_effect=[httpx.Response(500), httpx.Response(200, json={"idMessage": "ok"})]
        )
        mail = Mock()
        monkeypatch.setattr("app.alerts.channels.send_email", mail)
        await post(app_client, token, fx("text_received_mixed"))
        await run_all(deps)
        assert mail.call_count == 1 and mail.call_args.args[1] == "mail-parent@example.com"
        async with app_client.app.state.session_factory() as db:
            job = await db.scalar(select(Job).where(Job.type == "deliver_alert"))
            assert job is not None
            assert job.payload["delivered_recipients"] == ["email:mail-parent@example.com"]
            job.run_after = datetime(2000, 1, 1)
            await db.commit()
        await run_all(deps)
        assert green.call_count == 2 and mail.call_count == 1
        assert (await alerts(app_client))[0].delivery_status == "sent"
    finally:
        await deps.providers.aclose()


async def test_language_is_saved_only_for_the_signed_in_user(app_client: Any) -> None:
    uid = await parent(app_client, "language-parent")
    assert (
        await app_client.patch("/api/auth/language", json={"language": "he"})
    ).status_code == 200
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(User, uid)).language == "system"
    await app_client.post("/api/auth/logout")
    assert (
        await app_client.post(
            "/api/auth/login", json={"username": "language-parent", "password": "strong-password"}
        )
    ).status_code == 200
    assert (await app_client.get("/api/auth/me")).json()["language"] == "system"
    assert (
        await app_client.patch("/api/auth/language", json={"language": "en"})
    ).status_code == 200
    await app_client.post("/api/auth/logout")
    await app_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
    )
    assert (await app_client.get("/api/auth/me")).json()["language"] == "he"


@respx.mock
async def test_restricted_provider_does_not_block_another_parent_channel(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    try:
        monkeypatch.setattr("app.alerts.delivery.reserve", AsyncMock())
        await mixed_parents(app_client)
        respx.post(MOD_URL).mock(return_value=mod_response(harassment=0.9))
        green = respx.post("https://api.green-api.com/waInstance123/sendMessage/testtoken").mock(
            return_value=httpx.Response(403)
        )
        mail = Mock()
        monkeypatch.setattr("app.alerts.channels.send_email", mail)
        await post(app_client, token, fx("text_received_mixed"))
        await run_all(deps)
        assert green.call_count == 1 and mail.call_count == 1
        assert (await alerts(app_client))[0].delivery_status == "partial"
    finally:
        await deps.providers.aclose()
