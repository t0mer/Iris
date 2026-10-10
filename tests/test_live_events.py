import asyncio
import json
from typing import Any

import pytest
from sqlalchemy import select

from app import events as events_mod
from app.alerts.service import create_alert
from app.db.models import Chat, Message
from app.events import EventBus, TooManyClients, bus
from tests.test_webhooks import fx, make_instance, post


@pytest.fixture(autouse=True)
def _fresh_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import pairing

    async def idle_cleanup(_: Any) -> None:
        # These tests measure stream transactions, not the scheduler's own writes
        # and checked-out connections. Lifespan still starts and cancels this task.
        await asyncio.Future()

    monkeypatch.setattr(pairing, "cleanup_loop", idle_cleanup)
    if bus._timer is not None:
        bus._timer.cancel()
    bus._subs.clear()
    bus._topics.clear()
    bus._alert_ids.clear()
    bus._timer = None


class Stream:
    """The /api/events endpoint driven at the ASGI level (httpx buffers whole responses)."""

    def __init__(self, app: Any, cookie: str) -> None:
        self.app, self.cookie = app, cookie
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.task: asyncio.Task[None] | None = None
        self.status = 0
        self.headers: dict[str, str] = {}

    async def open(self) -> "Stream":
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"cookie", self.cookie.encode()), (b"host", b"test")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
        self.task = asyncio.create_task(self.app(scope, self.incoming.get, self.sent.put))
        start = await asyncio.wait_for(self.sent.get(), 3)
        self.status = start["status"]
        self.headers = {k.decode(): v.decode() for k, v in start["headers"]}
        return self

    async def read(self, wait: float = 3) -> str:
        msg = await asyncio.wait_for(self.sent.get(), wait)
        return msg.get("body", b"").decode()  # type: ignore[no-any-return]

    async def events(self, until: str, wait: float = 3) -> list[str]:
        out: list[str] = []
        while True:
            chunk = await self.read(wait)
            out.append(chunk)
            if until in chunk:
                return out

    async def close(self) -> None:
        await self.incoming.put({"type": "http.disconnect"})
        if self.task:
            await asyncio.wait_for(self.task, 3)


def cookie_of(c: Any) -> str:
    return "; ".join(f"{k}={v}" for k, v in c.cookies.items())


async def _open(c: Any) -> Stream:
    return await Stream(c.app, cookie_of(c)).open()


# --- the bus --------------------------------------------------------------------------------


async def test_changes_close_together_become_one_event() -> None:
    b = EventBus()
    sub = b.subscribe()
    b.publish("messages")
    b.publish("alerts", "stats")
    b.publish("messages")
    await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.2)
    assert sub.queue.get_nowait() == {"event": "change", "topics": ["alerts", "messages", "stats"]}
    assert sub.queue.empty()


async def test_a_new_alert_is_announced_with_only_its_id() -> None:
    b = EventBus()
    sub = b.subscribe()
    b.publish("alerts", alert_id=7)
    await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.2)
    got = [sub.queue.get_nowait(), sub.queue.get_nowait()]
    assert {"event": "alert", "id": 7} in got and sub.queue.empty()


async def test_unknown_topics_are_ignored_and_no_listener_means_no_work() -> None:
    b = EventBus()
    b.publish("messages")  # nobody listening: nothing is scheduled
    assert b._timer is None
    sub = b.subscribe()
    b.publish("secrets", "messages")
    await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.2)
    assert sub.queue.get_nowait() == {"event": "change", "topics": ["messages"]}


async def test_a_client_that_cannot_keep_up_is_dropped_not_waited_for() -> None:
    b = EventBus()
    slow, fast = b.subscribe(), b.subscribe()
    for _ in range(events_mod.QUEUE_SIZE):
        slow.queue.put_nowait({"event": "change", "topics": []})
    b.publish("messages")
    await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.2)
    assert b.clients == 1 and fast in b._subs and slow not in b._subs
    assert slow.queue.get_nowait() is None  # its stream ends, the browser reconnects


async def test_the_number_of_listeners_is_limited_and_unsubscribing_frees_a_place() -> None:
    b = EventBus()
    subs = [b.subscribe() for _ in range(events_mod.MAX_CLIENTS)]
    with pytest.raises(TooManyClients):
        b.subscribe()
    b.unsubscribe(subs[0])
    b.subscribe()


async def test_shutdown_ends_every_stream() -> None:
    b = EventBus()
    sub = b.subscribe()
    await b.close_all()
    assert sub.queue.get_nowait() is None and b.clients == 0


# --- the endpoint ---------------------------------------------------------------------------


async def test_the_stream_needs_a_login(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/events")).status_code == 401


async def test_the_stream_says_hello_with_the_right_headers(app_client: Any) -> None:
    s = await _open(app_client)
    try:
        assert s.status == 200 and s.headers["content-type"].startswith("text/event-stream")
        assert "no-cache" in s.headers["cache-control"]
        assert s.headers["x-accel-buffering"] == "no"
        assert s.headers["x-content-type-options"] == "nosniff"  # the security headers still apply
        first = "".join(await s.events("event: hello"))
        assert "retry: 3000" in first and "event: hello" in first
    finally:
        await s.close()


async def test_a_committed_change_is_pushed(app_client: Any) -> None:
    s = await _open(app_client)
    try:
        await s.events("event: hello")
        await make_instance(app_client, "Noa")
        text = "".join(await s.events("event: change"))
        data = json.loads(text.split("data: ", 1)[1].split("\n", 1)[0])
        assert "instances" in data["topics"] and "stats" in data["topics"]
    finally:
        await s.close()


async def test_a_new_alert_is_pushed_with_its_id_only(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    s = await _open(app_client)
    try:
        await s.events("event: hello")
        async with app_client.app.state.session_factory() as db:
            m = (await db.execute(select(Message))).scalar_one()
            alert = await create_alert(db, m, {"violence": 0.9})
        chunks = "".join(await s.events("event: alert"))
        assert f'event: alert\ndata: {{"id": {alert.id}}}' in chunks
        assert "violence" not in chunks and "mixed" not in chunks
    finally:
        await s.close()


async def test_a_rolled_back_change_is_not_announced(app_client: Any) -> None:
    s = await _open(app_client)
    try:
        await s.events("event: hello")
        async with app_client.app.state.session_factory() as db:
            db.add(Chat(wa_chat_id="never", name="x"))
            await db.flush()
            await db.rollback()
        await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.3)
        assert s.sent.empty()
    finally:
        await s.close()


async def test_nothing_in_the_stream_ever_contains_message_content(app_client: Any) -> None:
    import respx

    from app.classify.moderation import URL as MOD_URL
    from tests.test_alerts import msg_body, run_all, setup
    from tests.test_worker import mod_response

    deps, token, _ = await setup(app_client)
    s = await _open(app_client)
    secret = "TOPSECRETWORDSINMESSAGE"
    try:
        with respx.mock:
            respx.post(MOD_URL).mock(return_value=mod_response(violence=0.95))
            await post(app_client, token, msg_body("text_received_mixed", "LIVE1", secret))
            await run_all(deps)
        await asyncio.sleep(events_mod.COALESCE_SECONDS + 0.5)
        seen = ""
        while not s.sent.empty():
            seen += (await s.sent.get()).get("body", b"").decode()
    finally:
        await s.close()
        await deps.providers.aclose()
    assert "event: change" in seen and "event: alert" in seen
    for word in (secret, "violence", "Kid Tester", "Noa"):
        assert word not in seen


async def test_a_closed_connection_gives_its_place_back(app_client: Any) -> None:
    s = await _open(app_client)
    assert bus.clients == 1
    await s.close()
    assert bus.clients == 0


async def test_the_21st_open_portal_is_refused(app_client: Any) -> None:
    for _ in range(events_mod.MAX_CLIENTS):
        bus.subscribe()
    s = await _open(app_client)
    try:
        assert s.status == 429
    finally:
        await s.close()


async def test_shutdown_ends_an_open_stream(app_client: Any) -> None:
    s = await _open(app_client)
    await s.events("event: hello")
    await bus.close_all()
    assert s.task is not None
    await asyncio.wait_for(s.task, 3)


async def test_an_open_stream_holds_no_database_connection(app_client: Any) -> None:
    pool = app_client.app.state.engine.pool
    if not hasattr(pool, "checkedout"):
        pytest.skip("this pool does not report checked out connections")
    s = await _open(app_client)
    try:
        await s.events("event: hello")
        assert pool.checkedout() == 0
    finally:
        await s.close()


async def test_bulk_updates_that_skip_the_unit_of_work_are_announced(app_client: Any) -> None:
    from sqlalchemy import update

    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    s = await _open(app_client)
    try:
        await s.events("event: hello")
        async with app_client.app.state.session_factory() as db:
            await db.execute(update(Message).values(status="done"))
            await db.commit()
        text = "".join(await s.events("event: change"))
        assert '"messages"' in text
    finally:
        await s.close()
