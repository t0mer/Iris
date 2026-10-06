from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update

from app.alerts.service import create_alert
from app.db.models import Alert, Chat, Classification, Job, Message, MessageReceipt
from app.retention import run_retention
from app.settings_store import set_setting
from tests.test_alerts import msg_body
from tests.test_webhooks import make_instance, post

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def seed(c: Any, token: str, hashes: list[str], ages_days: list[int]) -> list[int]:
    import json

    for h, age in zip(hashes, ages_days, strict=True):
        b = json.loads(msg_body("text_received_mixed", h, f"retention text {h}"))
        b["data"]["timestamp"] = int((NOW - timedelta(days=age)).timestamp())
        await post(c, token, json.dumps(b).encode())
    async with c.app.state.session_factory() as s:
        return list((await s.execute(select(Message.id).order_by(Message.id))).scalars())


async def count(c: Any, model: Any) -> int:
    async with c.app.state.session_factory() as s:
        return int((await s.execute(select(func.count()).select_from(model))).scalar_one())


async def test_old_messages_deleted_with_their_rows_and_search_entries(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    ids = await seed(app_client, token, ["R1", "R2"], [100, 5])
    async with app_client.app.state.session_factory() as s:
        s.add(
            Classification(
                message_id=ids[0],
                stage="moderation",
                input_kind="text",
                model="m",
                scores={},
                flagged_categories=[],
                band="safe",
            )
        )
        await s.commit()
    res = await run_retention(app_client.app.state.session_factory, NOW)
    assert res["messages"] == 1
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(Message.id))).scalars().all() == [ids[1]]
    assert (
        await count(app_client, Classification) == 0
        and await count(app_client, MessageReceipt) == 1
    )
    async with app_client.app.state.session_factory() as s:
        hits = (
            await s.execute(
                text("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH 'retention'")
            )
        ).scalar_one()
        assert hits == 1  # only the recent message is still searchable


async def test_message_is_kept_while_any_alert_exists_then_goes_with_the_expired_alert(
    app_client: Any,
) -> None:
    """The alert row cascades with its message, so the message outlives its alert."""
    _, token = await make_instance(app_client)
    ids = await seed(app_client, token, ["K1", "K2", "K3"], [200, 200, 200])
    async with app_client.app.state.session_factory() as s:
        for mid in ids[:2]:
            m = await s.get(Message, mid)
            assert m
            await create_alert(s, m, {"violence": 0.9})
        await s.execute(update(Alert).where(Alert.message_id == ids[1]).values(status="dismissed"))
        await s.commit()
    factory = app_client.app.state.session_factory
    res = await run_retention(factory, NOW)
    async with factory() as s:
        left = (await s.execute(select(Message.id))).scalars().all()
    # 200-day-old messages, but both alerts are young: open AND dismissed alerts keep theirs
    assert left == ids[:2] and res["messages"] == 1  # only the alert-free message went
    assert await count(app_client, Alert) == 2
    # the dismissed alert passes its own retention: alert and message go in the same pass
    async with factory() as s:
        await s.execute(
            update(Alert).where(Alert.message_id == ids[1]).values(created_at=datetime(2025, 1, 1))
        )
        await s.commit()
    res = await run_retention(factory, NOW)
    async with factory() as s:
        assert (await s.execute(select(Message.id))).scalars().all() == [ids[0]]
    assert res["alerts"] == 1 and res["messages"] == 1 and await count(app_client, Alert) == 1


async def test_old_alerts_and_old_done_jobs_are_deleted(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    ids = await seed(app_client, token, ["A1", "A2"], [1, 1])
    async with app_client.app.state.session_factory() as s:
        for mid in ids:
            m = await s.get(Message, mid)
            assert m
            await create_alert(s, m, {"hate": 0.8})
        await s.execute(
            update(Alert).where(Alert.message_id == ids[0]).values(created_at=datetime(2025, 1, 1))
        )
        await s.execute(update(Job).values(status="done", created_at=datetime(2026, 9, 1)))
        s2 = await s.execute(select(Job.id).order_by(Job.id).limit(1))
        await s.execute(
            update(Job).where(Job.id == s2.scalar_one()).values(created_at=datetime(2026, 10, 5))
        )
        await s.commit()
    res = await run_retention(app_client.app.state.session_factory, NOW)
    assert res["alerts"] == 1 and res["jobs"] >= 1
    assert await count(app_client, Alert) == 1
    async with app_client.app.state.session_factory() as s:
        jobs = (await s.execute(select(Job.created_at))).scalars().all()
        assert all(
            j >= datetime(2026, 9, 29, tzinfo=UTC) for j in jobs
        )  # nothing older than 7 days remains


async def test_retention_windows_come_from_settings(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await seed(app_client, token, ["S1", "S2"], [20, 5])
    async with app_client.app.state.session_factory() as s:
        await set_setting(s, "retention.message_days", 10)
    assert (await run_retention(app_client.app.state.session_factory, NOW))["messages"] == 1
    assert await count(app_client, Message) == 1


async def test_retention_settings_validated(app_client: Any) -> None:
    for bad in (0, -1, 99999):
        r = await app_client.put(
            "/api/settings", json={"settings": {"retention.message_days": bad}}
        )
        assert r.status_code == 422
    ok = await app_client.put("/api/settings", json={"settings": {"retention.alert_days": 30}})
    assert ok.json()["retention.alert_days"] == 30


async def test_old_failed_jobs_and_empty_chats_are_removed(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await seed(app_client, token, ["F1", "F2"], [200, 1])
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(Job).where(Job.id == 1).values(status="failed", created_at=datetime(2026, 8, 1))
        )
        await s.execute(
            update(Job).where(Job.id == 2).values(status="dead", created_at=datetime(2026, 10, 1))
        )
        await s.commit()
    res = await run_retention(app_client.app.state.session_factory, NOW)
    async with app_client.app.state.session_factory() as s:
        jobs = (await s.execute(select(Job.id))).scalars().all()
    assert jobs == [2]  # the 66-day-old failed job is pruned, the recent dead one stays visible
    assert (
        res["messages"] == 1 and res["chats"] == 0
    )  # both messages share one chat; it still has one
    async with app_client.app.state.session_factory() as s:
        await s.execute(update(Message).values(sent_at=datetime(2020, 1, 1)))
        await s.commit()
    res = await run_retention(app_client.app.state.session_factory, NOW)
    assert res["chats"] == 1 and await count(app_client, Chat) == 0
