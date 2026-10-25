from typing import Any

from sqlalchemy import select

from app.db.models import Alert, Message, ReviewFeedback, StoredMedia
from tests.test_webhooks import count, fx, make_instance, post


async def test_skip_and_delete_shared_group_history(app_client: Any) -> None:
    c = app_client
    first, t1 = await make_instance(c, "Noa")
    second, t2 = await make_instance(c, "Dan")
    await post(c, t1, fx("group_text_received"))
    await post(c, t2, fx("group_text_received"))
    async with c.app.state.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        mid, chat_id = message.id, message.chat_id
        db.add(Alert(message_id=mid, kid_names=["Noa", "Dan"]))
        db.add(ReviewFeedback(message_id=mid, verdict="safe"))
        db.add(
            StoredMedia(
                message_id=mid,
                backend="local",
                key="test",
                content_type="image/png",
                kind="image",
                size_bytes=1,
                sha256="a" * 64,
            )
        )
        await db.commit()
    base = f"/api/messages/groups/{chat_id}/children"
    assert (await c.delete(f"{base}/{first}/history")).status_code == 409
    assert (await c.put(f"{base}/{first}", json={"skipped": True})).status_code == 200
    assert (await post(c, t1, fx("group_text_received"))).json()["result"] == "skipped"
    assert (await post(c, t2, fx("group_text_received"))).json()["result"] == "duplicate"
    result = await c.delete(f"{base}/{first}/history")
    assert result.json() == {"removed_receipts": 1, "deleted_messages": 0}
    assert (await c.get(f"/api/messages?instance_id={first}")).json()["total"] == 0
    assert (await c.get(f"/api/messages?instance_id={second}")).json()["total"] == 1
    assert (await c.get("/api/alerts")).json()["items"][0]["kid_names"] == ["Dan"]
    assert await count(c, ReviewFeedback) == 1
    await c.put(f"{base}/{second}", json={"skipped": True})
    assert (await c.delete(f"{base}/{second}/history")).json()["deleted_messages"] == 1
    assert await count(c, Message) == 0
    assert await count(c, Alert) == 0
    assert await count(c, ReviewFeedback) == 0
    async with c.app.state.session_factory() as db:
        assert (await db.scalars(select(StoredMedia))).one().purge
    assert len((await c.get("/api/messages/groups/skipped/list")).json()) == 2
    await c.put(f"{base}/{first}", json={"skipped": False})
    assert (await post(c, t1, fx("group_text_received"))).json()["result"] == "accepted"


async def test_direct_chat_cannot_be_skipped(app_client: Any) -> None:
    c = app_client
    child, token = await make_instance(c)
    await post(c, token, fx("text_received_mixed"))
    message = (await c.get("/api/messages")).json()["items"][0]
    assert (
        await c.put(
            f"/api/messages/groups/{message['chat_id']}/children/{child}", json={"skipped": True}
        )
    ).status_code == 404
    base = f"/api/messages/chats/{message['chat_id']}/children/{child}"
    assert (await c.put(base, json={"skipped": True})).status_code == 200
    assert (await post(c, token, fx("text_received_mixed"))).json()["result"] == "skipped"
    assert (await c.delete(f"{base}/history")).json()["deleted_messages"] == 1
    assert (await c.put(base, json={"skipped": False})).status_code == 200
    assert (await post(c, token, fx("text_received_mixed"))).json()["result"] == "accepted"
