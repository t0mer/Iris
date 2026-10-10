"""A message reported by two monitored sessions: media is fetched from whichever has it."""

import json
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Message
from app.jobs.handlers import Deps
from app.media.fetch import media_refs
from app.providers import Providers
from tests.test_media_pipeline import MEDIA, run_all
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response


async def two_sessions(c: Any) -> tuple[Deps, str, str]:
    """Session `a` (the sender) and session `b` (the receiver), on the same OpenWA."""
    await c.put("/api/settings", json={"settings": {"openai.api_key": "sk-test"}})
    tokens = []
    for name, sid in (("Noa", "a"), ("Dan", "b")):
        r = await c.post(
            "/api/instances",
            json={
                "kid_name": name,
                "openwa_base_url": "https://wa.x",
                "openwa_instance_id": sid,
                "openwa_api_key": "k",
            },
        )
        tokens.append(r.json()["webhook_url"].rsplit("/", 1)[1])
    deps = Deps(
        c.app.state.session_factory, Providers(), get_settings().key_bytes, get_settings().data_dir
    )
    return deps, tokens[0], tokens[1]


def received_view(fixture: str) -> bytes:
    """The same message as the receiving session reports it (its own chat id, `false_` ref)."""
    body = json.loads(fx(fixture))
    d = body["data"]
    h = d["id"].rsplit("_", 1)[1]
    d.update(id=f"false_111111111111111@lid_{h}", chatId="111111111111111@lid", fromMe=False)
    return json.dumps(body).encode()


def session_url(sid: str) -> str:
    return rf"https://wa\.x/api/sessions/{sid}/messages/.*/media"


async def the_message(c: Any) -> Message:
    async with c.app.state.session_factory() as s:
        return (await s.execute(select(Message))).scalar_one()


async def test_the_second_sessions_way_to_fetch_is_kept(app_client: Any) -> None:
    _, ta, tb = await two_sessions(app_client)
    await post(app_client, ta, fx("image_nocaption_received"))
    await post(app_client, tb, received_view("image_nocaption_received"))
    await post(app_client, tb, received_view("image_nocaption_received"))  # a redelivery
    refs = media_refs(await the_message(app_client))
    assert [r["instance_id"] for r in refs] == [1, 2]
    assert refs[1]["message_ref"].startswith("false_111111111111111@lid_")
    assert len(refs) == 2  # not added twice


def test_a_message_first_reported_without_media_takes_the_second_sessions_reference() -> None:
    from app.ingest.webhooks import _remember_media_ref
    from app.openwa.payloads import parse_event

    incoming = parse_event(json.loads(received_view("image_nocaption_received")))
    assert incoming is not None and incoming.media is not None
    m = Message(wa_message_id="h", chat_id=1, type="image", media=None)
    _remember_media_ref(m, 2, incoming)
    assert [r["instance_id"] for r in media_refs(m)] == [2]


@respx.mock
async def test_media_is_fetched_from_the_session_that_has_it(app_client: Any) -> None:
    deps, ta, tb = await two_sessions(app_client)
    respx.get(url__regex=session_url("a")).mock(return_value=httpx.Response(404))  # sender copy
    respx.get(url__regex=session_url("b")).mock(
        return_value=httpx.Response(
            200, content=(MEDIA / "image.png").read_bytes(), headers={"content-type": "image/png"}
        )
    )
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, ta, fx("image_nocaption_received"))
    await post(app_client, tb, received_view("image_nocaption_received"))
    assert await run_all(deps) == ["done"]
    msg = await the_message(app_client)
    assert msg.status == "done" and msg.verdict == "safe"


@respx.mock
async def test_it_fails_only_when_no_session_has_the_media(app_client: Any) -> None:
    deps, ta, tb = await two_sessions(app_client)
    await app_client.put("/api/settings", json={"settings": {"media.recovery_wait_seconds": 0}})
    respx.get(url__regex=r"https://wa\.x/api/sessions/.*/messages/.*/history").mock(
        return_value=httpx.Response(404)
    )
    for sid in ("a", "b"):
        respx.get(url__regex=session_url(sid)).mock(return_value=httpx.Response(404))
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, ta, fx("image_nocaption_received"))
    await post(app_client, tb, received_view("image_nocaption_received"))
    assert await run_all(deps) == ["failed"]
    msg = await the_message(app_client)
    assert msg.status == "failed"


@respx.mock
async def test_a_server_error_is_retried_not_passed_to_the_next_session(app_client: Any) -> None:
    deps, ta, tb = await two_sessions(app_client)
    first = respx.get(url__regex=session_url("a")).mock(return_value=httpx.Response(503))
    second = respx.get(url__regex=session_url("b")).mock(return_value=httpx.Response(200))
    respx.post(MOD_URL).mock(return_value=mod_response())
    await post(app_client, ta, fx("image_nocaption_received"))
    await post(app_client, tb, received_view("image_nocaption_received"))
    assert await run_all(deps) == ["queued"]  # transient: tried again later
    assert first.called and not second.called


@pytest.mark.parametrize("legacy", [{"instance_id": 1, "chat_id": "c", "message_ref": "true_c_h"}])
def test_messages_stored_before_this_change_still_work(legacy: dict[str, Any]) -> None:
    m = Message(wa_message_id="h", chat_id=1, type="image", media=legacy)
    assert media_refs(m) == [legacy]
