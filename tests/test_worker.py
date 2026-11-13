import asyncio
import json
from typing import Any

import httpx
import respx
from sqlalchemy import select

from app.classify.moderation import URL
from app.config import get_settings
from app.db.models import Classification, Job, Message
from app.jobs import queue
from app.jobs.handlers import Deps
from app.jobs.worker import WorkerPool, run_one
from app.providers import Providers
from tests.test_webhooks import fx, make_instance, post


def mod_response(**scores: float) -> httpx.Response:
    base = {"violence": 0.0, "hate": 0.0, **scores}
    return httpx.Response(
        200,
        json={
            "model": "omni-moderation-latest",
            "results": [
                {
                    "flagged": False,
                    "categories": {},
                    "category_scores": base,
                    "category_applied_input_types": {},
                }
            ],
        },
    )


async def setup(c: Any) -> tuple[Deps, str]:
    await c.put("/api/settings", json={"settings": {"openai.api_key": "sk-test"}})
    _, token = await make_instance(c, "Noa")
    deps = Deps(
        c.app.state.session_factory,
        Providers(),
        get_settings().key_bytes,
        data_dir=get_settings().data_dir,
    )
    return deps, token


async def drain(deps: Deps) -> list[str]:
    out = []
    while (job := await queue.claim(deps.session_factory)) is not None:
        out.append(await run_one(job, deps))
    return out


async def message_and_job(c: Any) -> tuple[Message, Job]:
    async with c.app.state.session_factory() as s:
        return (await s.execute(select(Message))).scalars().first(), (
            await s.execute(select(Job))
        ).scalars().first()  # type: ignore[return-value]


@respx.mock
async def test_safe_text_is_classified_and_done(app_client: Any) -> None:
    deps, token = await setup(app_client)
    route = respx.post(URL).mock(return_value=mod_response())
    await post(app_client, token, fx("text_received_mixed"))
    assert await drain(deps) == ["done"]
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalar_one()
        assert m.verdict == "safe" and m.status == "done"
        c = (await s.execute(select(Classification))).scalar_one()
        assert c.stage == "moderation" and c.band == "safe" and "_meta" in c.scores
    assert json.loads(route.calls.last.request.content)["model"] == "omni-moderation-latest"
    await deps.providers.aclose()


@respx.mock
async def test_inconclusive_triggers_context_stage_and_stores_both(app_client: Any) -> None:
    deps, token = await setup(app_client)
    earlier = json.loads(fx("text_received_mixed"))
    earlier["data"]["id"] = earlier["data"]["id"].replace("3EB07BE62351D41E6F0D35", "AAAA1111")
    earlier["data"]["timestamp"] -= 60
    earlier["data"]["body"] = "earlier line in the same chat"
    respx.post(URL).mock(
        side_effect=[mod_response(), mod_response(violence=0.3), mod_response(violence=0.01)]
    )
    await post(app_client, token, json.dumps(earlier).encode())
    await post(app_client, token, fx("text_received_mixed"))
    assert await drain(deps) == ["done", "done"]
    async with app_client.app.state.session_factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        target = msgs[1]
        cls = (
            (
                await s.execute(
                    select(Classification)
                    .where(Classification.message_id == target.id)
                    .order_by(Classification.id)
                )
            )
            .scalars()
            .all()
        )
        assert [c.stage for c in cls] == ["moderation", "context"]
        assert [c.band for c in cls] == ["inconclusive", "safe"]
        assert cls[1].context_message_ids == [msgs[0].id] and target.verdict == "safe"
    sent = [json.loads(c.request.content)["input"] for c in respx.calls]
    assert sent[2].startswith(
        '{"sender": "Kid Tester", "content": "earlier line in the same chat"}\n>>> '
    )
    await deps.providers.aclose()


@respx.mock
async def test_harmful_calls_hook_and_sets_verdict(app_client: Any) -> None:
    deps, token = await setup(app_client)
    seen: list[tuple[int, list[str]]] = []

    async def hook(_db: Any, message: Message, outcome: Any) -> None:
        seen.append((message.id, outcome.categories))

    deps.on_harmful = hook
    respx.post(URL).mock(return_value=mod_response(violence=0.95))
    await post(app_client, token, fx("text_received_mixed"))
    await drain(deps)
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(Message.verdict))).scalar_one() == "harmful"
    assert seen and seen[0][1] == ["violence"]
    await deps.providers.aclose()


async def test_missing_api_key_fails_job_and_message(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    deps = Deps(app_client.app.state.session_factory, Providers(), get_settings().key_bytes)
    await post(app_client, token, fx("text_received_mixed"))
    assert await drain(deps) == ["failed"]
    m, j = await message_and_job(app_client)
    assert m.status == "failed" and "not configured" in (j.last_error or "")


@respx.mock
async def test_rate_limit_requeues_with_retry_after(app_client: Any) -> None:
    deps, token = await setup(app_client)
    respx.post(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "120"}))
    await post(app_client, token, fx("text_received_mixed"))
    assert await drain(deps) == ["queued"]
    m, j = await message_and_job(app_client)
    assert j.status == "queued" and j.attempts == 1 and m.status == "processing"
    delay = (
        j.run_after - __import__("datetime").datetime.now(__import__("datetime").UTC)
    ).total_seconds()
    assert 100 < delay <= 120
    await deps.providers.aclose()


async def test_unknown_job_type_fails_permanently(app_client: Any) -> None:
    deps, _ = await setup(app_client)
    async with deps.session_factory() as s:
        await queue.enqueue(s, "mystery", {})
    assert await drain(deps) == ["failed"]


@respx.mock
async def test_worker_pool_processes_webhook_job_end_to_end(app_client: Any) -> None:
    deps, token = await setup(app_client)
    respx.post(URL).mock(return_value=mod_response())
    pool = WorkerPool(deps, size=2, poll_interval=0.02)
    await pool.start()
    try:
        assert pool.alive == 3  # Two classification workers and one reserved operations worker.
        await post(app_client, token, fx("text_received_mixed"))
        for _ in range(100):
            m, _ = await message_and_job(app_client)
            if m.status == "done":
                break
            await asyncio.sleep(0.05)
        assert m.status == "done" and m.verdict == "safe"
    finally:
        await pool.stop()
    assert pool.alive == 0
    await deps.providers.aclose()


@respx.mock
async def test_catch_up_runs_while_all_ai_workers_are_busy(app_client: Any, monkeypatch: Any):
    deps, token = await setup(app_client)
    started, finish = asyncio.Event(), asyncio.Event()

    async def delayed(_request: Any) -> httpx.Response:
        started.set()
        await finish.wait()
        return mod_response()

    async def no_due_schedules(_deps: Any) -> None:
        pass

    monkeypatch.setattr("app.jobs.worker.due_schedules", no_due_schedules)
    respx.post(URL).mock(side_effect=delayed)
    await post(app_client, token, fx("text_received_mixed"))
    pool = WorkerPool(deps, size=1, poll_interval=0.02)
    await pool.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        async with deps.session_factory() as db:
            jid = await queue.enqueue(db, "run_schedule", {"schedule_key": "openwa_recovery"})
        for _ in range(100):
            async with deps.session_factory() as db:
                scheduled = await db.get(Job, jid)
                if scheduled.status == "done":
                    break
            await asyncio.sleep(0.03)
        assert scheduled.status == "done"
        assert not finish.is_set()  # Scheduled work completed while inference remained blocked.
        finish.set()
        for _ in range(100):
            message, _ = await message_and_job(app_client)
            if message.status == "done":
                break
            await asyncio.sleep(0.03)
        assert message.status == "done"
        await pool.reconfigure(0, 0)
        assert pool.size == 0
    finally:
        finish.set()
        await pool.stop()
        await deps.providers.aclose()


@respx.mock
async def test_failing_harmful_hook_does_not_fail_the_message(app_client: Any) -> None:
    deps, token = await setup(app_client)

    async def boom(*_: Any) -> None:
        raise RuntimeError("alert service down")

    deps.on_harmful = boom
    respx.post(URL).mock(return_value=mod_response(violence=0.95))
    await post(app_client, token, fx("text_received_mixed"))
    assert await drain(deps) == ["done"]
    m, _ = await message_and_job(app_client)
    assert m.status == "done" and m.verdict == "harmful"
    async with deps.session_factory() as db:
        pending = (await db.scalars(select(Job).where(Job.type == "prepare_alert"))).one()
        assert pending.status == "queued"
        pending.run_after = queue._naive(queue._now())
        await db.commit()
    assert await drain(deps) == ["done"]
    from app.db.models import Alert

    async with deps.session_factory() as db:
        assert (await db.scalars(select(Alert))).one().message_id == m.id
        assert len((await db.scalars(select(Classification))).all()) == 1
    await deps.providers.aclose()


async def test_database_busy_is_retried_not_failed(app_client: Any) -> None:
    from sqlalchemy.exc import OperationalError

    deps, token = await setup(app_client)
    await post(app_client, token, fx("text_received_mixed"))

    async def locked(*_: Any) -> None:
        raise OperationalError("stmt", {}, Exception("database is locked"))

    job = await queue.claim(deps.session_factory)
    assert job and await run_one(job, deps, {"process_message": locked}) == "queued"


async def test_reprocess_blocked_while_job_active(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))  # creates a queued job
    assert (await app_client.post("/api/messages/1/reprocess")).status_code == 409


async def test_provider_key_rotation_keeps_old_client_until_close() -> None:
    p = Providers()
    a = p.moderation("k1")
    assert p.moderation("k1") is a
    b = p.moderation("k2")
    assert b is not a and not a._client.is_closed  # in-flight requests may still use it
    await p.aclose()
    assert a._client.is_closed and b._client.is_closed


async def test_handler_timeout_stops_renewing_and_retries(
    app_client: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("IRIS_JOB_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("IRIS_JOB_HEARTBEAT_SECONDS", "1")
    get_settings.cache_clear()
    deps, token = await setup(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    cancelled = asyncio.Event()

    async def stuck(*_: Any) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    job = await queue.claim(deps.session_factory)
    assert job and await run_one(job, deps, {"process_message": stuck}) == "queued"
    assert cancelled.is_set()
    await deps.providers.aclose()


async def test_notification_job_does_not_block_reprocess(app_client: Any) -> None:
    from datetime import UTC, datetime

    from app.db.models import Chat

    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="test", is_group=False)
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id, wa_message_id="test", type="text", sent_at=datetime.now(UTC)
        )
        db.add(message)
        await db.flush()
        db.add(Job(type="notify_change", status="running", payload={"message_id": message.id}))
        await db.commit()
        assert not await queue.has_active_job(db, message.id)
