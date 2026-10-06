import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from loguru import logger
from sqlalchemy import select, update

from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Alert, Job, Message
from app.jobs import queue
from app.jobs.handlers import Deps
from app.jobs.worker import run_one
from app.providers import Providers
from app.settings_store import set_setting
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response

IMAGE_PNG = (Path(__file__).parent / "fixtures" / "media" / "image.png").read_bytes()
OWA = "https://wa.x"
SEND_URL = f"{OWA}/api/sessions/sender-sess/messages/send-text"


async def setup(
    c: Any, recipient: str | None = "972501234567", cooldown: int = 10
) -> tuple[Deps, str, int]:
    """OpenAI key, a kid instance (webhook token) and a separate alert-sender instance."""
    await c.put("/api/settings", json={"settings": {"openai.api_key": "sk-test"}})
    kid = (
        await c.post(
            "/api/instances",
            json={
                "kid_name": "Noa",
                "openwa_base_url": OWA,
                "openwa_instance_id": "s",
                "openwa_api_key": "k",
            },
        )
    ).json()
    sender = (
        await c.post(
            "/api/instances",
            json={
                "kid_name": "Alerts",
                "openwa_base_url": OWA,
                "openwa_instance_id": "sender-sess",
                "openwa_api_key": "owa",
            },
        )
    ).json()
    settings: dict[str, Any] = {"alerts.cooldown_minutes": cooldown}
    if recipient:
        settings |= {"alerts.sender_instance_id": sender["id"], "alerts.recipient": recipient}
    await c.put("/api/settings", json={"settings": settings})
    deps = Deps(
        c.app.state.session_factory,
        Providers(),
        get_settings().key_bytes,
        get_settings().data_dir,
        get_settings().public_base_url,
    )
    return deps, kid["webhook_url"].rsplit("/", 1)[1], sender["id"]


async def run_all(deps: Deps) -> list[str]:
    out = []
    while (job := await queue.claim(deps.session_factory)) is not None:
        out.append(await run_one(job, deps))
    return out


async def alerts(c: Any) -> list[Alert]:
    async with c.app.state.session_factory() as s:
        return list((await s.execute(select(Alert).order_by(Alert.id))).scalars())


def msg_body(fixture: str, hash_: str, text: str, ts_add: int = 0) -> bytes:
    b = json.loads(fx(fixture))
    b["data"]["id"] = b["data"]["id"].rsplit("_", 1)[0] + "_" + hash_
    b["data"]["body"] = text
    b["data"]["timestamp"] += ts_add
    return json.dumps(b).encode()


@respx.mock
async def test_harmful_message_creates_alert_and_delivers_whatsapp_text(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95, hate=0.3))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "x"}))
    await post(app_client, token, fx("text_received_mixed"))
    statuses = await run_all(deps)
    assert statuses == ["done", "done"]  # classification, then delivery
    (a,) = await alerts(app_client)
    assert a.delivery_status == "sent" and a.notified_at and a.categories == ["violence"]
    assert a.kid_names == ["Noa"] and a.sender_name == "Kid Tester" and "mixed" in (a.quote or "")
    req = send.calls.last.request
    assert req.headers["x-api-key"] == "owa"
    sent = json.loads(req.content)
    assert sent["chatId"] == "972501234567@c.us"
    assert sent["text"].startswith(
        "⚠️ Iris alert\nKid: Noa\nChat: Kid Tester (direct)\nFrom: Kid Tester\n"
    )
    assert (
        f"Open: http://localhost:8080/alerts/{a.id}?s=" in sent["text"]
        and "violence (0.95)" in sent["text"]
    )
    await deps.providers.aclose()


@respx.mock
async def test_alert_is_created_once_per_message_even_if_reprocessed(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    await app_client.post("/api/messages/1/reprocess")
    await run_all(deps)
    assert len(await alerts(app_client)) == 1
    await deps.providers.aclose()


@respx.mock
async def test_delivery_not_configured_is_recorded_not_queued(app_client: Any) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    await post(app_client, token, fx("text_received_mixed"))
    assert await run_all(deps) == ["done"]  # only the classification job exists
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and a.delivery_error == "alert delivery not configured"
    await deps.providers.aclose()


@respx.mock
async def test_review_item_alerts_only_when_opted_in(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(
        return_value=mod_response(violence=0.4)
    )  # inconclusive twice -> review
    respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert await alerts(app_client) == []
    await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": True}})
    await app_client.post("/api/messages/1/reprocess")
    await run_all(deps)
    (a,) = await alerts(app_client)
    assert a.categories == ["violence"]
    await deps.providers.aclose()


# --- cooldown ---------------------------------------------------------------------------------


@respx.mock
async def test_cooldown_suppresses_then_plus_n_more_line(app_client: Any) -> None:
    deps, token, _ = await setup(app_client, cooldown=10)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    for i, h in enumerate(("AAA1", "AAA2", "AAA3")):
        await post(app_client, token, msg_body("text_received_mixed", h, f"threat number {i}", i))
        await run_all(deps)
    a1, a2, a3 = await alerts(app_client)
    assert [a.delivery_status for a in (a1, a2, a3)] == ["sent", "suppressed", "suppressed"]
    assert send.call_count == 1
    # the window passes; the next alert goes out and mentions the two it swallowed
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(Alert)
            .where(Alert.id == a1.id)
            .values(notified_at=datetime.now(UTC) - timedelta(minutes=30))
        )
        await s.commit()
    await post(app_client, token, msg_body("text_received_mixed", "AAA4", "threat number 4", 4))
    await run_all(deps)
    assert send.call_count == 2
    assert (
        "+2 more alerts in this chat since last notification"
        in json.loads(send.calls.last.request.content)["text"]
    )
    await deps.providers.aclose()


@respx.mock
async def test_resend_bypasses_cooldown_and_failed_alert_can_be_resent(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    for i, h in enumerate(("BBB1", "BBB2")):
        await post(app_client, token, msg_body("text_received_mixed", h, f"threat {i}", i))
        await run_all(deps)
    a1, a2 = await alerts(app_client)
    assert a2.delivery_status == "suppressed"
    r = await app_client.post(f"/api/alerts/{a2.id}/resend")
    assert r.status_code == 200
    await run_all(deps)
    assert (await alerts(app_client))[1].delivery_status == "sent" and send.call_count == 2
    await deps.providers.aclose()


# --- delivery failures ------------------------------------------------------------------------


@respx.mock
async def test_server_error_is_retried_then_marked_failed_after_three_attempts(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    respx.post(SEND_URL).mock(return_value=httpx.Response(503, json={"message": "engine busy"}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)  # classify + first delivery attempt
    for _ in range(2):
        async with app_client.app.state.session_factory() as s:
            await s.execute(
                update(Job).where(Job.status == "queued").values(run_after=datetime(2000, 1, 1))
            )
            await s.commit()
        await run_all(deps)
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and "engine busy" in (a.delivery_error or "")
    async with app_client.app.state.session_factory() as s:
        job = (await s.execute(select(Job).where(Job.type == "deliver_alert"))).scalar_one()
        assert job.status == "dead" and job.attempts == 3
    await deps.providers.aclose()


@respx.mock
async def test_rejected_delivery_fails_immediately_and_can_be_resent_once_fixed(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(400, json={"message": "Session is not active"})
    )
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    (a,) = await alerts(app_client)
    assert a.delivery_status == "failed" and "Session is not active" in (a.delivery_error or "")
    route.mock(return_value=httpx.Response(201, json={}))
    assert (await app_client.post(f"/api/alerts/{a.id}/resend")).status_code == 200
    await run_all(deps)
    assert (await alerts(app_client))[0].delivery_status == "sent"
    await deps.providers.aclose()


# --- redaction (spec 8.5) ---------------------------------------------------------------------


@respx.mock
async def test_sexual_minors_text_is_redacted_everywhere_and_never_logged_or_forwarded(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    secret = "SECRETEXPLICITWORDS"
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.9}))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        await post(app_client, token, msg_body("text_received_mixed", "CCC1", secret))
        await run_all(deps)
    finally:
        logger.remove(sink)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert (
            m.redacted
            and m.text == "[redacted]"
            and m.transcript == "[redacted]"
            and m.media is None
        )
        (a,) = (await s.execute(select(Alert))).scalars().all()
        assert a.quote is None and a.categories == ["sexual/minors"]
    sent_text = json.loads(send.calls.last.request.content)["text"]
    assert secret not in sent_text and "Content withheld (sexual content)" in sent_text
    assert not any(secret in line for line in logs)
    assert secret not in (await app_client.get("/api/messages")).text
    assert (await app_client.get("/api/messages", params={"q": secret})).json()["total"] == 0
    assert (await app_client.get("/api/messages", params={"q": "redacted"})).json()["total"] == 0
    assert (await app_client.post("/api/messages/1/reprocess")).status_code == 409
    await deps.providers.aclose()


@respx.mock
async def test_sexual_image_is_redacted_but_sexual_text_alone_is_not(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(sexual=0.9))
    respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    respx.get(url__regex=r"https://wa\.x/api/sessions/s/messages/.*/media").mock(
        return_value=httpx.Response(200, content=IMAGE_PNG)
    )
    await post(app_client, token, msg_body("image_caption_sent", "DDD1", "secretcaption"))
    await post(app_client, token, msg_body("text_received_mixed", "DDD2", "adult but plain text"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        image, text = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        assert image.type == "image" and image.redacted and image.text == "[redacted]"
        assert text.type == "text" and not text.redacted and text.text == "adult but plain text"
    await deps.providers.aclose()


async def test_alert_content_never_includes_redacted_text_in_api(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    async with app_client.app.state.session_factory() as s:
        from app.alerts.service import create_alert

        m = (await s.execute(select(Message))).scalar_one()
        await create_alert(s, m, {"sexual/minors": 0.8})
    detail = (await app_client.get("/api/alerts/1")).json()
    assert detail["quote"] is None and detail["redacted"] is True
    assert "mixed" not in json.dumps(detail, ensure_ascii=False)


@pytest.mark.parametrize(
    "recipient", ["972501234567", "+972501234567", "972501234567@c.us", "120363@g.us"]
)
def test_recipient_chat_id_normalisation(recipient: str) -> None:
    from app.alerts.delivery import recipient_chat_id

    got = recipient_chat_id(recipient)
    assert got.endswith(("@c.us", "@g.us")) and "+" not in got
    assert recipient_chat_id(got) == got


async def test_set_setting_helper_still_available() -> None:
    assert set_setting is not None


def _revoke(fixture: str) -> bytes:
    raw = json.loads(fx("message_revoked"))
    raw["data"]["revokedId"] = json.loads(fx(fixture))["data"]["id"]
    return json.dumps(raw).encode()


@respx.mock
async def test_deleted_alerted_message_sends_a_follow_up_without_content(app_client: Any) -> None:
    from app.alerts import ALERT_PREFIX
    from app.alerts.format import is_own_alert

    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert send.call_count == 1
    await post(app_client, token, _revoke("text_received_mixed"))
    assert await run_all(deps) == ["done"]
    assert send.call_count == 2
    text = json.loads(send.calls.last.request.content)["text"]
    assert text.startswith(ALERT_PREFIX) and "deleted for everyone" in text
    assert "mixed" not in text and "Kid: Noa" in text
    assert is_own_alert(text, get_settings().key_bytes)  # the loop guard still recognises it
    await deps.providers.aclose()


@respx.mock
async def test_edited_alerted_message_sends_a_follow_up(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_sent_he"))
    await run_all(deps)
    await post(app_client, token, fx("message_edited"))
    await run_all(deps)  # the follow-up and the re-check of the edited text
    texts = [json.loads(c.request.content)["text"] for c in send.calls]
    assert any("was edited by the sender" in t for t in texts)
    await deps.providers.aclose()


@respx.mock
async def test_a_rejected_follow_up_fails_visibly(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client)
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    send.mock(return_value=httpx.Response(400, json={"message": "bad"}))
    await post(app_client, token, _revoke("text_received_mixed"))
    assert await run_all(deps) == ["failed"]  # visible on the Jobs page
    await deps.providers.aclose()
