import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select, update

from app.alerts.recipients import recipients
from app.classify.moderation import URL as MOD_URL
from app.db.models import Job, SendingBudget
from tests.test_alerts import SEND_URL, alerts, run_all, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


async def advance_queue(deps: Any) -> None:
    async with deps.session_factory() as db:
        past = datetime.now(UTC) - timedelta(seconds=1)
        await db.execute(update(SendingBudget).values(next_allowed=past))
        await db.execute(update(Job).where(Job.status == "queued").values(run_after=past))
        await db.commit()


def test_deduplicate_equivalent_parent_numbers():
    assert recipients("+1 5550100101, 15550100101@c.us\n15550100102") == [
        "15550100101@c.us",
        "15550100102@c.us",
    ]


@pytest.mark.parametrize("value", ["not-a-phone", "15550100101, broken", "123"])
def test_invalid_recipient_rejects_entire_list(value):
    with pytest.raises(ValueError):
        recipients(value)


@respx.mock
async def test_retry_only_failed_parent_and_preserves_target_snapshot(app_client: Any):
    deps, token, _ = await setup(app_client, recipient="15550100101, 15550100102")
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    delivered: list[str] = []
    fail_second = True

    def send(request: httpx.Request):
        target = json.loads(request.content)["chatId"]
        if target == "15550100102@c.us" and fail_second:
            return httpx.Response(503, json={"message": "engine busy"})
        delivered.append(target)
        return httpx.Response(201, json={"id": "sent"})

    respx.post(SEND_URL).mock(side_effect=send)
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert delivered == ["15550100101@c.us"]
    async with deps.session_factory() as db:
        job = (await db.scalars(select(Job).where(Job.type == "deliver_alert"))).one()
        assert job.payload["delivered_recipients"] == ["15550100101@c.us"]
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    await advance_queue(deps)
    await run_all(deps)  # The second parent returns 503 on its first actual attempt.
    await advance_queue(deps)
    # Editing the setting during a retry must not add a new, unintended recipient.
    await app_client.put("/api/settings", json={"settings": {"alerts.recipient": "15550100103"}})
    fail_second = False
    await run_all(deps)
    # Removing a recipient must revoke the pending send, including persisted snapshots.
    assert delivered == ["15550100101@c.us"]
    assert (await alerts(app_client))[0].delivery_status == "suppressed"


@respx.mock
async def test_rejected_first_parent_does_not_block_second(app_client: Any):
    deps, token, _ = await setup(app_client, recipient="15550100101, 15550100102")
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    targets: list[str] = []

    def send(request: httpx.Request):
        target = json.loads(request.content)["chatId"]
        targets.append(target)
        return httpx.Response(
            400 if target == "15550100101@c.us" else 201,
            json={"message": "Recipient unavailable", "id": "sent"},
        )

    respx.post(SEND_URL).mock(side_effect=send)
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    await advance_queue(deps)
    await run_all(deps)
    assert targets == ["15550100101@c.us", "15550100102@c.us"]
    assert (await alerts(app_client))[0].delivery_status == "partial"


@respx.mock
async def test_test_button_sends_to_each_unique_parent(app_client: Any):
    deps, _, sender_id = await setup(app_client)
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    response = await app_client.post(
        "/api/settings/test/alert",
        json={
            "sender_instance_id": sender_id,
            "recipient": "+15550100101, 15550100101@c.us, 15550100102",
        },
    )
    assert response.json()["ok"] and "queued" in response.json()["detail"]
    assert send.call_count == 1
    await advance_queue(deps)
    await run_all(deps)
    assert [json.loads(call.request.content)["chatId"] for call in send.calls] == [
        "15550100101@c.us",
        "15550100102@c.us",
    ]


@respx.mock
async def test_child_assignment_filters_alert_and_manual_resend(app_client: Any):
    deps, token, _ = await setup(app_client, recipient="15550100101, 15550100102")
    await app_client.put(
        "/api/settings", json={"settings": {"alerts.recipient_children": {"15550100102": []}}}
    )
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert [json.loads(call.request.content)["chatId"] for call in send.calls] == [
        "15550100101@c.us"
    ]
    alert = (await alerts(app_client))[0]
    await app_client.put(
        "/api/settings",
        json={"settings": {"alerts.recipient_children": {"15550100101": [], "15550100102": []}}},
    )
    await app_client.post(f"/api/alerts/{alert.id}/resend")
    await advance_queue(deps)
    await run_all(deps)
    assert send.call_count == 1


@pytest.mark.parametrize("value", [{"15550100101": [-1]}, {"15550100101": [True]}, {"bad": [1]}])
async def test_invalid_child_assignment_is_rejected(app_client: Any, value: Any):
    response = await app_client.put(
        "/api/settings", json={"settings": {"alerts.recipient_children": value}}
    )
    assert response.status_code == 422


@respx.mock
async def test_assignment_applies_to_followup_after_parent_is_removed(app_client: Any):
    from tests.test_alerts import _revoke

    deps, token, _ = await setup(app_client, recipient="15550100101")
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert send.call_count == 1
    await app_client.put(
        "/api/settings", json={"settings": {"alerts.recipient_children": {"15550100101": []}}}
    )
    await post(app_client, token, _revoke("text_received_mixed"))
    await advance_queue(deps)
    await run_all(deps)
    assert send.call_count == 1
    await deps.providers.aclose()


async def test_unknown_child_assignment_cannot_attach_to_a_future_phone(app_client: Any):
    response = await app_client.put(
        "/api/settings", json={"settings": {"alerts.recipient_children": {"15550100101": [999]}}}
    )
    assert response.status_code == 422
