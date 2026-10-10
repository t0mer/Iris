from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.alerts.service import create_alert
from app.db.models import Instance, Job, Message
from tests.test_alerts import msg_body
from tests.test_webhooks import fx, make_instance, post


async def test_stats_empty_database(app_client: Any) -> None:
    s = (await app_client.get("/api/stats")).json()
    assert s["children"] == s["parent_recipients"] == s["alert_phones"] == 0
    assert s["alert_sender_configured"] is False
    assert s["messages_today"] == 0 and s["queue_depth"] == 0 and s["failed_jobs"] == 0
    assert s["delivery_configured"] is False and s["instances"] == 0 and s["review_queue"] == 0


async def test_quiet_phone_is_not_reported_as_missing_webhook(
    app_client: Any, monkeypatch: Any
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "monitoring_silence_minutes", 60)
    iid, _ = await make_instance(app_client, "Quiet")
    async with app_client.app.state.session_factory() as db:
        await db.execute(
            update(Instance)
            .where(Instance.id == iid)
            .values(last_webhook_at=datetime.now(UTC) - timedelta(hours=3))
        )
        await db.commit()
    stats = (await app_client.get("/api/stats")).json()
    assert stats["monitoring_window_minutes"] == 60
    assert stats["silent_instances"] == 0


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
        msgs[1].status = "failed"  # terminal AI failure is ready for a human decision
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


async def test_setup_counts_separate_children_parents_and_senders(app_client: Any) -> None:
    await make_instance(app_client, "Child")
    parent = (
        await app_client.post(
            "/api/instances",
            json={
                "kid_name": "Sender",
                "role": "parent",
                "openwa_base_url": "https://wa.example",
                "openwa_instance_id": "sender",
            },
        )
    ).json()
    response = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "alerts.sender_instance_id": parent["id"],
                "alerts.recipient": "15550100101, 15550100102",
            }
        },
    )
    assert response.status_code == 200
    stats = (await app_client.get("/api/stats")).json()
    assert stats["children"] == 1
    assert stats["parent_recipients"] == 2
    assert stats["alert_phones"] == 1
    assert stats["alert_sender_configured"] is True
    await app_client.delete(f"/api/instances/{parent['id']}")
    stats = (await app_client.get("/api/stats")).json()
    assert stats["alert_sender_configured"] is False
    assert stats["alert_phones"] == 0


async def test_timeline_filters_message_receipts_without_duplicate_counts(app_client: Any):
    first, token = await make_instance(app_client, "First")
    second, token2 = await make_instance(app_client, "Second")
    await post(app_client, token, msg_body("text_received_mixed", "CHILD1", "one"))
    await post(app_client, token2, msg_body("text_received_mixed", "CHILD2", "two"))
    for child in (first, second):
        value = (await app_client.get(f"/api/stats/timeline?instance_id={child}")).json()
        assert sum(day["other"] for day in value["days"]) == 1
    value = (await app_client.get("/api/stats/timeline")).json()
    assert sum(day["other"] for day in value["days"]) == 2


def test_storage_distinguishes_missing_from_empty_and_counts_databases(tmp_path):
    from app.api.stats import measure_directory

    assert measure_directory(None)["bytes"] is None
    assert measure_directory(tmp_path / "missing")["bytes"] is None
    folder = tmp_path / "provider"
    folder.mkdir()
    (folder / "main.sqlite").write_bytes(b"db")
    (folder / "media.bin").write_bytes(b"media")
    value = measure_directory(folder)
    assert value["bytes"] == 7 and value["database_bytes"] == 2


def test_provider_storage_uses_fresh_metadata_and_rejects_stale_report(tmp_path):
    import json
    import time

    from app.api.stats import provider_storage

    report = tmp_path / "meter.json"
    report.write_text(
        json.dumps({"bytes": 100, "database_bytes": 40, "measured_at": int(time.time())})
    )
    assert provider_storage(None, report)["bytes"] == 100
    report.write_text(json.dumps({"bytes": 100, "database_bytes": 40, "measured_at": 0}))
    assert provider_storage(None, report)["bytes"] is None


async def test_chats_filters_match_the_same_message(app_client: Any) -> None:
    iid, token = await make_instance(app_client, "Noa")
    other_id, other_token = await make_instance(app_client, "Dan")
    await post(app_client, token, fx("group_text_received"))
    await post(app_client, other_token, fx("text_received_mixed"))
    async with app_client.app.state.session_factory() as db:
        messages = list(await db.scalars(select(Message).order_by(Message.id)))
        messages[0].verdict = "harmful"
        messages[0].sender_name = "Dana"
        messages[1].verdict = "safe"
        messages[1].sender_name = "Other"
        group_id = messages[0].chat_id
        await db.commit()
    filters = {"instance_id": iid, "type": "text", "verdict": "harmful", "sender": "Dana"}
    chats = (await app_client.get("/api/chats", params=filters)).json()
    assert [c["id"] for c in chats] == [group_id]
    assert chats[0]["message_count"] == 1
    for change in (
        {"instance_id": other_id},
        {"type": "video"},
        {"verdict": "safe"},
        {"sender": "missing"},
        {"from": "2100-01-01T00:00:00Z"},
        {"q": "!!!"},
    ):
        assert (await app_client.get("/api/chats", params=filters | change)).json() == []
    # Use the existing indexed Hebrew/English search implementation identically to Messages.
    for q in ("שלום", "hello"):
        params = {"q": q}
        matches = (await app_client.get("/api/messages", params=params)).json()["items"]
        chats = (await app_client.get("/api/chats", params=params)).json()
        assert {c["id"] for c in chats} == {m["chat_id"] for m in matches}
    assert len((await app_client.get("/api/chats")).json()) == 2


def test_disk_capacity_reports_real_volume_and_missing_path(tmp_path: Any) -> None:
    import shutil

    from app.api.stats import disk_capacity

    expected = shutil.disk_usage(tmp_path)
    result = disk_capacity(tmp_path)
    assert result["total_bytes"] == expected.total
    assert result["used_bytes"] is not None and result["free_bytes"] is not None
    assert result["status"] == "measured"
    assert disk_capacity(tmp_path / "missing")["total_bytes"] is None
