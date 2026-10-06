from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.alerts.service import create_alert
from app.db.models import Instance, Job, Message
from tests.test_alerts import msg_body
from tests.test_webhooks import fx, make_instance, post


async def test_stats_empty_database(app_client: Any) -> None:
    s = (await app_client.get("/api/stats")).json()
    assert s["messages_today"] == 0 and s["queue_depth"] == 0 and s["failed_jobs"] == 0
    assert s["delivery_configured"] is False and s["instances"] == 0 and s["review_queue"] == 0


async def test_stats_counts(app_client: Any) -> None:
    _, token = await make_instance(app_client, "Noa")
    await make_instance(app_client, "Silent")  # never receives a webhook
    now = datetime.now(UTC)
    for i, age_days in enumerate((0, 3, 20)):
        body = msg_body("text_received_mixed", f"ST0{i}", f"m{i}")
        import json

        b = json.loads(body)
        b["data"]["timestamp"] = int((now - timedelta(days=age_days, minutes=1)).timestamp())
        await post(app_client, token, json.dumps(b).encode())
    async with app_client.app.state.session_factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        msgs[1].verdict = "review"
        await create_alert(s, msgs[0], {"violence": 0.9})
        await s.execute(update(Job).where(Job.id == 2).values(status="failed"))
        await s.commit()
    st = (await app_client.get("/api/stats")).json()
    assert st["messages_7d"] == 2 and st["messages_today"] >= 1
    assert st["alerts_by_status"] == {"new": 1} and st["alerts_by_delivery"] == {"failed": 1}
    assert st["review_queue"] == 1 and st["failed_jobs"] == 1
    assert st["queue_depth"] == 2  # three ingest jobs, one of them marked failed
    assert st["instances"] == 2 and st["silent_instances"] == 1


async def test_chats_list_with_kids_and_counts(app_client: Any) -> None:
    _, t1 = await make_instance(app_client, "Noa")
    _, t2 = await make_instance(app_client, "Dan")
    await post(app_client, t1, fx("group_text_received"))
    await post(app_client, t2, fx("group_text_received"))  # same group: two kids
    await post(app_client, t1, fx("text_received_mixed"))
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message).where(Message.chat_id == 1))).scalars().first()
        assert m
        await create_alert(s, m, {"hate": 0.8})
    chats = (await app_client.get("/api/chats")).json()
    group = next(c for c in chats if c["is_group"])
    assert [k["kid_name"] for k in group["kids"]] == ["Noa", "Dan"]
    assert group["message_count"] == 1 and group["alert_count"] == 1
    direct = next(c for c in chats if not c["is_group"])
    assert (
        direct["message_count"] == 1
        and direct["alert_count"] == 0
        and direct["name"] == "Kid Tester"
    )


async def test_stats_and_chats_require_auth(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/stats")).status_code == 401
    assert (await app_client.get("/api/chats")).status_code == 401
    assert Instance and Job


async def test_timeline_is_zero_filled_and_split_by_verdict(app_client: Any) -> None:
    from datetime import date

    _, token = await make_instance(app_client)
    now = datetime.now(UTC)
    for i, age in enumerate((0, 0, 2, 2)):
        import json

        b = json.loads(msg_body("text_received_mixed", f"TL0{i}", f"t{i}"))
        b["data"]["timestamp"] = int((now - timedelta(days=age, minutes=5)).timestamp())
        await post(app_client, token, json.dumps(b).encode())
    async with app_client.app.state.session_factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        for m, v in zip(msgs, ("safe", "harmful", "review", "safe"), strict=True):
            m.verdict = v
        await create_alert(s, msgs[1], {"violence": 0.9})
        await s.commit()
    t = (await app_client.get("/api/stats/timeline", params={"days": 5})).json()
    assert len(t["days"]) == 5 and t["timezone"] == "Asia/Jerusalem"
    days = {d["date"]: d for d in t["days"]}
    assert days[min(days)]["safe"] == 0 and days[min(days)]["alerts"] == 0  # zero filled
    assert [d["date"] for d in t["days"]] == sorted(days)  # oldest first, consecutive
    assert date.fromisoformat(max(days)) >= date.fromisoformat(min(days))
    totals = {
        k: sum(d[k] for d in t["days"]) for k in ("safe", "review", "harmful", "other", "alerts")
    }
    assert totals == {"safe": 2, "review": 1, "harmful": 1, "other": 0, "alerts": 1}


async def test_timeline_buckets_in_the_configured_time_zone(app_client: Any) -> None:
    """21:30 UTC is already tomorrow in Jerusalem (UTC+3 in summer): the parent's day wins."""
    import json

    _, token = await make_instance(app_client)
    from zoneinfo import ZoneInfo

    jerusalem = ZoneInfo("Asia/Jerusalem")
    local_today = datetime.now(jerusalem).date()
    stamp = datetime.combine(local_today, datetime.min.time(), tzinfo=jerusalem) + timedelta(
        minutes=30
    )
    b = json.loads(msg_body("text_received_mixed", "TZ01", "just after local midnight"))
    b["data"]["timestamp"] = int(stamp.timestamp())  # 00:30 local = previous day in UTC
    await post(app_client, token, json.dumps(b).encode())
    jer = (await app_client.get("/api/stats/timeline", params={"days": 2})).json()["days"]
    assert jer[-1]["other"] == 1 and jer[0]["other"] == 0  # counted on the local day
    await app_client.put("/api/settings", json={"settings": {"alerts.timezone": "UTC"}})
    utc = (await app_client.get("/api/stats/timeline", params={"days": 2})).json()
    assert utc["timezone"] == "UTC"
    assert sum(d["other"] for d in utc["days"]) == 1


async def test_timeline_validates_days_and_requires_auth(app_client: Any) -> None:
    for bad in (0, 91, -1):
        assert (
            await app_client.get("/api/stats/timeline", params={"days": bad})
        ).status_code == 422
    assert len((await app_client.get("/api/stats/timeline")).json()["days"]) == 14  # default
    app_client.cookies.clear()
    assert (await app_client.get("/api/stats/timeline")).status_code == 401
