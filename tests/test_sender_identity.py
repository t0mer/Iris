from typing import Any

import respx

from app.security.two_factor import GREEN_API_KEY
from tests.test_alert_readiness import parent, provider

BASE = "https://api.green-api.com/waInstance123"


@respx.mock
async def test_user_number_cannot_be_green_sender_in_either_order(app_client: Any) -> None:
    respx.get(BASE + "/getSettings/testtoken").respond(200, json={"wid": "15550100102@c.us"})
    config = {"instance_id": "123", "token": "testtoken"}
    assert (await app_client.put("/api/users/security/whatsapp", json=config)).status_code == 200
    invalid = await app_client.post(
        "/api/users",
        json={
            "username": "parent",
            "role": "parent",
            "password": "strong-password",
            "whatsapp_number": "+15550100102",
        },
    )
    assert invalid.status_code == 422 and "must differ" in invalid.text
    valid = await app_client.post(
        "/api/users",
        json={
            "username": "parent",
            "role": "parent",
            "password": "strong-password",
            "whatsapp_number": "+15550100103",
        },
    )
    assert valid.status_code == 201
    respx.get(BASE + "/getSettings/testtoken").respond(200, json={"wid": "15550100103@c.us"})
    reversed_conflict = await app_client.put("/api/users/security/whatsapp", json=config)
    assert reversed_conflict.status_code == 422 and "personal WhatsApp" in reversed_conflict.text
    assert not (await app_client.get("/api/users/security/config")).json()["green_api"]["verified"]


@respx.mock
async def test_sender_identity_is_read_only_and_contact_approval_still_requires_confirmation(
    app_client: Any,
) -> None:
    uid = await parent(app_client, "parent", "+15550100102")
    await provider(app_client, GREEN_API_KEY)
    sent = respx.post(BASE + "/sendInteractiveButtons/testtoken").respond(
        200, json={"idMessage": "test"}
    )
    respx.get(BASE + "/getStateInstance/testtoken").respond(
        200, json={"stateInstance": "authorized"}
    )
    response = await app_client.post(
        f"/api/users/{uid}/approve-contact", json={"channel": "whatsapp"}
    )
    assert response.status_code == 200 and sent.called
    users = (await app_client.get("/api/users")).json()
    assert not next(u for u in users if u["id"] == uid)["whatsapp_verified"]
