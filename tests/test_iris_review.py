import asyncio
from datetime import UTC, datetime
from typing import Any

import respx
from sqlalchemy import func, select

from app.classify.moderation import URL
from app.config import get_settings
from app.db.models import Alert, Chat, Classification, Job, Message, ReviewFeedback
from app.jobs.handlers import Deps
from app.jobs.queue import claim, enqueue
from app.jobs.worker import run_one
from app.providers import Providers
from tests.test_worker import mod_response


async def seed(client: Any) -> tuple[int, int]:
    async with client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="review@g.us")
        db.add(chat)
        await db.flush()
        ai = Message(
            chat_id=chat.id,
            wa_message_id="ai",
            type="text",
            text="AI target",
            sent_at=datetime.now(UTC),
            status="pending",
        )
        human = Message(
            chat_id=chat.id,
            wa_message_id="human",
            type="text",
            text="Human target",
            sent_at=datetime.now(UTC),
            status="done",
            verdict="review",
        )
        db.add_all([ai, human])
        await db.flush()
        await enqueue(db, "process_message", {"message_id": ai.id})
        return ai.id, human.id


async def test_human_details_validation_history_and_redaction(app_client: Any):
    from app.alerts.service import redact_message
    from app.audit import safe_value

    _, human = await seed(app_client)
    assert (
        await app_client.post(
            f"/api/review/{human}", json={"resolution": "safe", "categories": ["violence"]}
        )
    ).status_code == 422
    assert (
        await app_client.post(
            f"/api/review/{human}", json={"resolution": "harmful", "categories": ["invented"]}
        )
    ).status_code == 422
    response = await app_client.post(
        f"/api/review/{human}", json={"resolution": "safe", "explanation": "זו בדיחה בין חברים"}
    )
    assert response.status_code == 200
    row = (await app_client.get("/api/review?view=responses")).json()["items"][0]
    assert row["human_feedback"]["explanation"] == "זו בדיחה בין חברים"
    assert safe_value("explanation", "private") == "[present]"
    async with app_client.app.state.session_factory() as db:
        message = await db.get(Message, human)
        redact_message(message)
        await db.commit()
        assert (await db.get(ReviewFeedback, human)).explanation is None


async def test_ai_and_human_queues_are_disjoint_and_skip_moves_message(app_client: Any):
    ai, human = await seed(app_client)
    pending = (await app_client.get("/api/review")).json()
    thinking = (await app_client.get("/api/review?view=ai")).json()
    assert [r["message"]["id"] for r in pending["items"]] == [human]
    assert [r["message"]["id"] for r in thinking["items"]] == [ai]
    response = await app_client.post(f"/api/review/{ai}", json={"resolution": "safe"})
    assert response.status_code == 409
    response = await app_client.post(f"/api/review/{ai}/skip-ai")
    assert response.status_code == 200
    assert (await app_client.get("/api/review?view=ai")).json()["total"] == 0
    assert (await app_client.get("/api/review")).json()["total"] == 2
    async with app_client.app.state.session_factory() as db:
        assert (await db.scalar(select(Job))).status == "cancelled"
    assert (
        await app_client.post(f"/api/review/{ai}", json={"resolution": "safe"})
    ).status_code == 200
    assert (await app_client.post(f"/api/review/{human}/skip-ai")).status_code == 409


async def test_active_job_hides_even_done_status_from_human_queue(app_client: Any):
    ai, _ = await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        m = await db.get(Message, ai)
        m.status, m.verdict = "done", "review"
        await db.commit()
    assert (await app_client.get("/api/review")).json()["total"] == 1
    assert (await app_client.get("/api/review?view=ai")).json()["total"] == 1
    stats = (await app_client.get("/api/stats")).json()
    assert stats["iris_review_queue"] == 1 and stats["review_queue"] == 1


async def test_skip_recheck_preserves_existing_human_decision(app_client: Any):
    ai, _ = await seed(app_client)
    async with app_client.app.state.session_factory() as db:
        db.add(ReviewFeedback(message_id=ai, verdict="safe"))
        await db.commit()
    response = await app_client.post(f"/api/review/{ai}/skip-ai")
    assert response.json()["human_review_view"] == "responses"
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(Message, ai)).verdict == "safe"
    app_client.cookies.clear()
    assert (await app_client.post(f"/api/review/{ai}/skip-ai")).status_code == 401


@respx.mock
async def test_skipped_running_ai_cannot_overwrite_human_decision_or_create_alert(app_client: Any):
    ai, _ = await seed(app_client)
    await app_client.put("/api/settings", json={"settings": {"openai.api_key": "test-key"}})
    started, finish = asyncio.Event(), asyncio.Event()

    async def delayed(_request):
        started.set()
        await finish.wait()
        return mod_response(violence=0.99)

    respx.post(URL).mock(side_effect=delayed)
    factory = app_client.app.state.session_factory
    cfg = get_settings()
    deps = Deps(factory, Providers(), cfg.key_bytes, cfg.data_dir)
    job = await claim(factory, types=("process_message",))
    task = asyncio.create_task(run_one(job, deps))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        assert (await app_client.post(f"/api/review/{ai}/skip-ai")).status_code == 200
        assert (
            await app_client.post(f"/api/review/{ai}", json={"resolution": "safe"})
        ).status_code == 200
        finish.set()
        assert await task == "superseded"
        async with factory() as db:
            assert (await db.get(Message, ai)).verdict == "safe"
            assert await db.scalar(select(func.count()).select_from(Alert)) == 0
            assert await db.scalar(select(func.count()).select_from(Classification)) == 0
    finally:
        finish.set()
        await task
        await deps.providers.aclose()
