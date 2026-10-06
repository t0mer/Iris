from typing import Any
from urllib.parse import quote

import httpx
import pytest
import respx
from sqlalchemy import select

from app import chats
from app.chats import resolve_group_names
from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Alert, Chat, Message
from app.openwa.client import OpenWAClient, OpenWAError
from tests.test_alerts import run_all, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response

GROUP = "972500000099-1500000000@g.us"  # the id in the sanitized group fixture
URL = f"https://wa.x/api/sessions/s/groups/{quote(GROUP, safe='')}"


@pytest.fixture(autouse=True)
def _fresh_cooldowns() -> None:
    chats._last_try.clear()


async def named(c: Any, chat_wa_id: str = GROUP) -> str | None:
    async with c.app.state.session_factory() as s:
        return (
            await s.execute(select(Chat.name).where(Chat.wa_chat_id == chat_wa_id))
        ).scalar_one()


async def resolve(c: Any) -> int:
    return await resolve_group_names(c.app.state.session_factory, get_settings().key_bytes)


@respx.mock
async def test_client_reads_the_group_subject() -> None:
    c = OpenWAClient("https://wa.x", "key")
    respx.get(URL).mock(
        return_value=httpx.Response(200, json={"id": GROUP, "name": "  Class 6B  "})
    )
    assert await c.get_group_name("s", GROUP) == "Class 6B"
    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": {"name": "Wrapped"}}))
    assert await c.get_group_name("s", GROUP) == "Wrapped"
    respx.get(URL).mock(return_value=httpx.Response(200, json={"id": GROUP}))
    assert await c.get_group_name("s", GROUP) is None
    respx.get(URL).mock(return_value=httpx.Response(404, json={"message": "not found"}))
    with pytest.raises(OpenWAError):
        await c.get_group_name("s", GROUP)
    await c.aclose()


@respx.mock
async def test_unnamed_group_gets_its_name_from_openwa(app_client: Any) -> None:
    _, token, _ = await setup(app_client, recipient=None)
    await post(app_client, token, fx("group_text_received"))
    assert await named(app_client) is None  # the webhook alone cannot know it
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"name": "Class 6B"}))
    assert await resolve(app_client) == 1
    assert await named(app_client) == "Class 6B"
    assert route.calls.last.request.headers["x-api-key"] == "k"  # the kid's own OpenWA key
    assert await resolve(app_client) == 0  # already named: no second lookup
    assert route.call_count == 1
    assert (await app_client.get("/api/chats")).json()[0]["name"] == "Class 6B"


@respx.mock
async def test_direct_chats_are_never_looked_up(app_client: Any) -> None:
    _, token, _ = await setup(app_client, recipient=None)
    await post(app_client, token, fx("text_received_mixed"))
    route = respx.get(url__regex=r"https://wa\.x/api/sessions/s/groups/.*").mock(
        return_value=httpx.Response(200, json={"name": "x"})
    )
    assert await resolve(app_client) == 0 and route.call_count == 0


@respx.mock
async def test_alerts_made_before_the_name_was_known_are_updated(app_client: Any) -> None:
    from app.alerts.service import create_alert

    _, token, _ = await setup(app_client, recipient=None)
    await post(app_client, token, fx("group_text_received"))
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        a = await create_alert(s, m, {"violence": 0.9})
        assert a.chat_name is None
    respx.get(URL).mock(return_value=httpx.Response(200, json={"name": "Class 6B"}))
    await resolve(app_client)
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(Alert.chat_name))).scalar_one() == "Class 6B"


@respx.mock
async def test_lookup_failure_is_tolerated_and_retried_only_after_a_pause(app_client: Any) -> None:
    _, token, _ = await setup(app_client, recipient=None)
    await post(app_client, token, fx("group_text_received"))
    route = respx.get(URL).mock(return_value=httpx.Response(404, json={"message": "gone"}))
    assert await resolve(app_client) == 0 and await named(app_client) is None  # no crash
    assert await resolve(app_client) == 0 and route.call_count == 1  # paused: not asked again
    chats._last_try.clear()  # the pause has passed
    route.mock(return_value=httpx.Response(200, json={"name": "Back again"}))
    assert await resolve(app_client) == 1 and await named(app_client) == "Back again"


@respx.mock
async def test_a_disabled_instance_is_not_used(app_client: Any) -> None:
    _, token, _ = await setup(app_client, recipient=None)
    await post(app_client, token, fx("group_text_received"))
    await app_client.patch("/api/instances/1", json={"enabled": False})  # instance 1 is the child's
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"name": "x"}))
    assert await resolve(app_client) == 0 and route.call_count == 0


@respx.mock
async def test_processing_a_group_message_names_the_group_before_the_alert_quotes_it(
    app_client: Any,
) -> None:
    deps, token, _ = await setup(app_client, recipient=None)
    respx.get(URL).mock(return_value=httpx.Response(200, json={"name": "Class 6B"}))
    respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
    await post(app_client, token, fx("group_text_received"))
    await run_all(deps)
    (alert,) = (await app_client.get("/api/alerts")).json()["items"]
    assert alert["chat_name"] == "Class 6B"
    msg = (await app_client.get("/api/messages")).json()["items"][0]
    assert msg["chat_name"] == "Class 6B" and msg["is_group"] is True
    await deps.providers.aclose()
