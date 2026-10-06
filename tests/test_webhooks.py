import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.api.instances import webhook_secret
from app.config import get_settings
from app.db.models import Chat, ChatInstance, Instance, Job, Message, MessageReceipt
from app.settings_store import set_setting

FIX = Path(__file__).parent / "fixtures" / "openwa"


def fx(name: str) -> bytes:
    return (FIX / f"{name}.json").read_bytes()


async def make_instance(c: Any, name: str = "Noa") -> tuple[int, str]:
    r = await c.post(
        "/api/instances",
        json={"kid_name": name, "openwa_base_url": "https://wa.x", "openwa_instance_id": "s"},
    )
    out = r.json()
    return out["id"], out["webhook_url"].rsplit("/", 1)[1]


async def count(c: Any, model: Any) -> int:
    async with c.app.state.session_factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


def post(c: Any, token: str, raw: bytes, **headers: str) -> Any:
    return c.post(
        f"/webhooks/{token}", content=raw, headers={"content-type": "application/json", **headers}
    )


async def test_unknown_token_404(app_client: Any) -> None:
    assert (await post(app_client, "nope", fx("text_received_mixed"))).status_code == 404


async def test_disabled_instance_404(app_client: Any) -> None:
    iid, token = await make_instance(app_client)
    await app_client.patch(f"/api/instances/{iid}", json={"enabled": False})
    assert (await post(app_client, token, fx("text_received_mixed"))).status_code == 404


async def test_text_message_stored_and_job_enqueued(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    r = await post(app_client, token, fx("text_received_mixed"))
    assert r.json() == {"result": "accepted"}
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.type == "text" and m.status == "pending" and m.sender_name == "Kid Tester"
        chat = await s.get(Chat, m.chat_id)
        assert chat and chat.name == "Kid Tester" and not chat.is_group
        job = (await s.execute(select(Job))).scalar_one()
        assert job.type == "process_message" and job.payload["message_id"] == m.id
        inst = (await s.execute(select(Instance))).scalar_one()
        assert inst.last_webhook_at is not None


async def test_from_me_uses_kid_name(app_client: Any) -> None:
    _, token = await make_instance(app_client, "Noa")
    await post(app_client, token, fx("text_sent_he"))
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.from_me and m.sender_name == "Noa"


async def test_same_group_message_from_two_instances_one_message_two_receipts(
    app_client: Any,
) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    assert (await post(app_client, t1, fx("group_text_received"))).json()["result"] == "accepted"
    assert (await post(app_client, t2, fx("group_text_received"))).json()["result"] == "duplicate"
    assert await count(app_client, Message) == 1
    assert await count(app_client, MessageReceipt) == 2
    assert await count(app_client, ChatInstance) == 2
    assert await count(app_client, Job) == 1


async def test_redelivery_same_instance_is_duplicate(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    r = await post(app_client, token, fx("text_received_mixed"))
    assert r.json()["result"] == "duplicate"
    assert await count(app_client, Job) == 1 and await count(app_client, MessageReceipt) == 1


async def test_non_message_events_ignored_but_touch_last_webhook(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    r = await post(app_client, token, fx("message_reaction"))
    assert r.json() == {"result": "ignored"}
    assert await count(app_client, Message) == 0


async def test_malformed_payload_returns_200_rejected(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    assert (await post(app_client, token, b"not json")).json() == {"result": "rejected"}
    bad = json.dumps({"event": "message.received", "data": {"id": "x"}}).encode()
    assert (await post(app_client, token, bad)).json() == {"result": "rejected"}


async def test_signature_checked_when_present(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    raw = fx("text_received_mixed")
    good = (
        "sha256="
        + hmac.new(webhook_secret(get_settings(), token).encode(), raw, hashlib.sha256).hexdigest()
    )
    assert (
        await post(app_client, token, raw, **{"x-openwa-signature": "sha256=" + "0" * 64})
    ).status_code == 401
    assert (await post(app_client, token, raw, **{"x-openwa-signature": good})).status_code == 200


async def test_alert_loop_chat_skipped(app_client: Any) -> None:
    iid, token = await make_instance(app_client)
    async with app_client.app.state.session_factory() as s:
        await set_setting(s, "alerts.sender_instance_id", iid)
        await set_setting(
            s, "alerts.recipient", "222222222222222"
        )  # same digits as the fixture chat
    r = await post(app_client, token, fx("text_sent_he"))
    assert r.json() == {"result": "skipped"} and await count(app_client, Message) == 0


def signed_alert_text(alert_id: int = 7) -> str:
    from app.alerts.format import with_signed_link

    return with_signed_link(
        "⚠️ Iris alert\nKid: Noa", "http://localhost:8080", get_settings().key_bytes, alert_id
    )


async def test_own_signed_alert_skipped_on_any_instance(app_client: Any) -> None:
    """The recipient may itself be a monitored number, so the guard is not tied to the sender."""
    _, token = await make_instance(app_client)
    for fixture in ("text_sent_he", "text_received_mixed"):
        body = json.loads(fx(fixture))
        body["data"]["body"] = signed_alert_text()
        r = await post(app_client, token, json.dumps(body).encode())
        assert r.json() == {"result": "skipped"}
    assert await count(app_client, Message) == 0


async def test_lookalike_alert_with_bad_signature_is_still_classified(app_client: Any) -> None:
    """Someone typing the alert format must not be able to dodge monitoring."""
    _, token = await make_instance(app_client)
    body = json.loads(fx("text_received_mixed"))
    body["data"]["body"] = "⚠️ Iris alert\nOpen: http://localhost:8080/alerts/7?s=0000000000000000"
    assert (await post(app_client, token, json.dumps(body).encode())).json() == {
        "result": "accepted"
    }


async def test_alert_recipient_on_other_instance_not_skipped(app_client: Any) -> None:
    iid, _ = await make_instance(app_client, "Sender")
    _, token = await make_instance(app_client, "Kid")
    async with app_client.app.state.session_factory() as s:
        await set_setting(s, "alerts.sender_instance_id", iid)
        await set_setting(s, "alerts.recipient", "222222222222222")
    assert (await post(app_client, token, fx("text_sent_he"))).json() == {"result": "accepted"}


async def test_scope_filters(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    async with app_client.app.state.session_factory() as s:
        await set_setting(s, "scope.monitor_from_me", False)
        await set_setting(s, "scope.monitor_groups", False)
    assert (await post(app_client, token, fx("text_sent_he"))).json()["result"] == "skipped"
    assert (await post(app_client, token, fx("group_text_received"))).json()["result"] == "skipped"
    assert (await post(app_client, token, fx("text_received_mixed"))).json()["result"] == "accepted"


async def test_oversized_body_413(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    r = await post(app_client, token, b"x" * (25 * 1024 * 1024 + 1))
    assert r.status_code == 413


async def test_signature_mandatory_after_iris_registers_webhook(app_client: Any) -> None:
    import httpx
    import respx

    iid, token = await make_instance(app_client)
    await app_client.patch(f"/api/instances/{iid}", json={"openwa_api_key": "k"})
    with respx.mock:
        respx.get("https://wa.x/api/sessions/s/webhooks").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.post("https://wa.x/api/sessions/s/webhooks").mock(
            return_value=httpx.Response(201, json={"id": "w"})
        )
        assert (await app_client.post(f"/api/instances/{iid}/register-webhook")).status_code == 200
    raw = fx("text_received_mixed")
    assert (await post(app_client, token, raw)).status_code == 401  # unsigned is rejected now
    good = (
        "sha256="
        + hmac.new(webhook_secret(get_settings(), token).encode(), raw, hashlib.sha256).hexdigest()
    )
    assert (await post(app_client, token, raw, **{"x-openwa-signature": good})).status_code == 200
    # Rotation invalidates the registered secret, so unsigned deliveries are accepted again
    # until the webhook is re-registered.
    new = (
        (await app_client.post(f"/api/instances/{iid}/rotate-token"))
        .json()["webhook_url"]
        .rsplit("/", 1)[1]
    )
    assert (await post(app_client, new, fx("text_sent_he"))).status_code == 200


async def test_streamed_body_without_content_length_is_capped(app_client: Any) -> None:
    _, token = await make_instance(app_client)

    async def chunks() -> Any:
        for _ in range(26):
            yield b"x" * (1024 * 1024)

    r = await app_client.post(f"/webhooks/{token}", content=chunks())
    assert r.status_code == 413


async def test_concurrent_deliveries_of_same_new_group_message(app_client: Any) -> None:
    import asyncio

    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    r1, r2 = await asyncio.gather(
        post(app_client, t1, fx("group_text_received")),
        post(app_client, t2, fx("group_text_received")),
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert sorted([r1.json()["result"], r2.json()["result"]]) == ["accepted", "duplicate"]
    assert await count(app_client, Message) == 1 and await count(app_client, MessageReceipt) == 2
    assert await count(app_client, Job) == 1


def _received_view_of(fixture: str) -> bytes:
    """The same message as the OTHER monitored session sees it: same hash, other chat id."""
    body = json.loads(fx(fixture))
    d = body["data"]
    h = d["id"].rsplit("_", 1)[1]
    d.update(
        id=f"false_111111111111111@lid_{h}",
        chatId="111111111111111@lid",
        from_="111111111111111@lid",
        fromMe=False,
        contact={"pushName": "Noa", "name": "Noa"},
    )
    d["from"] = d.pop("from_")
    return json.dumps(body).encode()


async def test_message_between_two_monitored_kids_is_one_message_with_two_receipts(
    app_client: Any,
) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    # Dan's session receives it first, then Noa's session reports having sent it.
    assert (await post(app_client, t2, _received_view_of("text_sent_he"))).json()[
        "result"
    ] == "accepted"
    assert (await post(app_client, t1, fx("text_sent_he"))).json()["result"] == "duplicate"
    assert await count(app_client, Message) == 1 and await count(app_client, MessageReceipt) == 2
    assert await count(app_client, Job) == 1  # classified once, so it can alert only once
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.from_me is True and m.sender_name == "Noa"  # author resolved to the sending kid
        assert await count(app_client, ChatInstance) == 2  # both kids linked to the chat
    listing = (await app_client.get("/api/messages")).json()["items"]
    assert [k["kid_name"] for k in listing[0]["kids"]] == ["Noa", "Dan"]


async def test_sender_view_first_then_receiver_view_is_also_one_message(app_client: Any) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    await post(app_client, t1, fx("text_sent_he"))
    assert (await post(app_client, t2, _received_view_of("text_sent_he"))).json()[
        "result"
    ] == "duplicate"
    assert await count(app_client, Message) == 1 and await count(app_client, MessageReceipt) == 2


async def test_real_alert_link_pasted_under_other_text_is_still_classified(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    link = signed_alert_text().split("\n\nOpen: ")[1]
    body = json.loads(fx("text_received_mixed"))
    body["data"]["body"] = f"⚠️ Iris alert\nI will hurt you\n\nOpen: {link}"
    assert (await post(app_client, token, json.dumps(body).encode())).json() == {
        "result": "accepted"
    }
