import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import URL as MOD_URL
from app.classify.ollama import OllamaModerator
from app.classify.stages import ModerationStage, StageContext
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.config import validate_public_base_url
from app.db.models import Chat, Message, ReviewFeedback
from tests.test_alerts import SEND_URL, run_all, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


@pytest.mark.parametrize(
    "value",
    [
        "file:///etc/passwd",
        "https://user:pass@iris.example.com",
        "https://iris.example.com?q=code",
        "https://iris.example.com/#x",
        "missing-scheme",
    ],
)
def test_public_url_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        validate_public_base_url(value)


@respx.mock
async def test_domain_changes_live_delivery_without_restart(app_client: Any) -> None:
    deps, token, _ = await setup(app_client)
    url = "https://iris.example.com"
    r = await app_client.put(
        "/api/settings", json={"settings": {"runtime.public_base_url": url + "/"}}
    )
    assert r.status_code == 200
    assert r.json()["runtime.public_base_url"] == url
    assert deps.public_base_url != url  # old worker dependency still exists
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={"id": "sent"}))
    await post(app_client, token, fx("text_received_mixed"))
    await run_all(deps)
    assert send.called
    assert url + "/alerts/" in json.loads(send.calls[0].request.content)["text"]
    assert (await app_client.get("/api/instances")).json()[0]["webhook_url"].startswith(url)
    assert (
        await app_client.put(
            "/api/settings", json={"settings": {"runtime.public_base_url": "javascript:alert(1)"}}
        )
    ).status_code == 422


@respx.mock
async def test_review_labels_never_enter_ollama_prompt(app_client: Any) -> None:
    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="calibration@g.us", is_group=True)
        db.add(chat)
        await db.flush()
        target = None
        for i, (text, label, redacted, revoked) in enumerate(
            [
                ("friendly example", "safe", False, False),
                ("threat example", "harmful", False, False),
                ("private redacted example", "harmful", True, False),
                ("revoked example", "safe", False, True),
                ("new target", None, False, False),
            ]
        ):
            m = Message(
                chat_id=chat.id,
                wa_message_id=f"calibration-{i}",
                text=text,
                type="text",
                sent_at=datetime.now(UTC),
                redacted=redacted,
                revoked_at=datetime.now(UTC) if revoked else None,
            )
            db.add(m)
            await db.flush()
            if label:
                db.add(ReviewFeedback(message_id=m.id, verdict=label))
            else:
                target = m
        await db.commit()
        assert target
        scores = {cat: 0.0 for cat in DEFAULT_THRESHOLDS}
        scores["violence"] = 0.95
        request = respx.post("https://ollama.example/api/chat").mock(
            return_value=httpx.Response(200, json={"message": {"content": json.dumps(scores)}})
        )
        moderator = OllamaModerator("https://ollama.example", "model")
        try:
            context = StageContext(
                db=db,
                moderator=moderator,
                model="model",
                thresholds=DEFAULT_THRESHOLDS,
                context_window_size=8,
                context_max_age=timedelta(hours=6),
            )
            result = await ModerationStage().run(target, context)
        finally:
            await moderator.aclose()
        assert result and result.band == "harmful"  # a safe example does not bypass classification
        body = json.loads(request.calls[0].request.content)
        instructions = body["messages"][0]["content"]
        assert "friendly example" not in instructions and "threat example" not in instructions
        assert (
            "private redacted example" not in instructions and "revoked example" not in instructions
        )
        assert context.thresholds == DEFAULT_THRESHOLDS
        await db.delete(
            (
                await db.execute(select(Message).where(Message.text == "friendly example"))
            ).scalar_one()
        )
        await db.commit()
        assert len((await db.execute(select(ReviewFeedback))).scalars().all()) == 3


@respx.mock
async def test_existing_lan_webhook_restored_with_https_public_links(app_client: Any) -> None:
    from tests.test_instances import BODY

    instance = (await app_client.post("/api/instances", json=BODY)).json()
    token = instance["webhook_url"].rsplit("/", 1)[1]
    public = "https://iris.example.com"
    internal = "http://192.0.2.10:8182"
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {"runtime.public_base_url": public, "runtime.webhook_base_url": internal}
        },
    )
    assert response.status_code == 200
    base = "https://wa.example.com/api/sessions/sess-1/webhooks"
    respx.get(base).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "existing-hook", "url": internal + "/webhooks/" + token, "events": []}],
        )
    )
    update_hook = respx.put(base + "/existing-hook").mock(
        return_value=httpx.Response(200, json={"id": "existing-hook"})
    )
    registered = await app_client.post(f"/api/instances/{instance['id']}/register-webhook")
    assert registered.status_code == 200
    assert update_hook.called
    assert registered.json() == {"webhook_id": "existing-hook"}
    assert (await app_client.get(f"/api/instances/{instance['id']}")).json()[
        "webhook_url"
    ] == internal + "/webhooks/" + token
    assert (await app_client.get("/api/settings")).json()["runtime.public_base_url"] == public
    # Clearing the database override falls back to the public address when no env override exists.
    cleared = await app_client.put(
        "/api/settings", json={"settings": {"runtime.webhook_base_url": ""}}
    )
    assert cleared.status_code == 200
    assert (
        (await app_client.get(f"/api/instances/{instance['id']}"))
        .json()["webhook_url"]
        .startswith(public)
    )
