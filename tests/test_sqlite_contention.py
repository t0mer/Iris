import asyncio
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Job, ScheduleRun, Setting
from app.jobs import queue
from app.schedules import due_schedules, tracked


@pytest.fixture
async def database(tmp_path):
    path = tmp_path / "contention.db"
    url = f"sqlite+aiosqlite:///{path}"
    await asyncio.to_thread(upgrade_head, url)
    engine = make_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def short_timeout(conn, _):
        conn.execute("PRAGMA busy_timeout=10")

    factory = make_session_factory(engine)
    try:
        yield path, factory
    finally:
        await engine.dispose()


def hold_write_lock(path):
    connection = sqlite3.connect(path)
    connection.execute("BEGIN IMMEDIATE")

    async def release():
        await asyncio.sleep(0.12)
        connection.rollback()
        connection.close()

    return asyncio.create_task(release())


async def test_claim_retries_real_lock_without_claiming_twice(database):
    path, factory = database
    async with factory() as db:
        first = await queue.enqueue(db, "process_message", {})
        second = await queue.enqueue(db, "process_message", {})
    release = hold_write_lock(path)
    claimed = await queue.claim(factory)
    await release
    assert claimed.id == first and claimed.attempts == 1
    async with factory() as db:
        assert (await db.get(Job, second)).status == "queued"


async def test_schedule_dispatch_retries_and_does_not_duplicate(database):
    path, factory = database
    deps = SimpleNamespace(session_factory=factory)
    now = datetime(2026, 10, 15, 21, tzinfo=UTC)
    release = hold_write_lock(path)
    await due_schedules(deps, now)
    await release
    await due_schedules(deps, now)
    async with factory() as db:
        jobs = list(await db.scalars(select(Job)))
        keys = [job.payload["schedule_key"] for job in jobs]
        assert keys and len(keys) == len(set(keys))
        for key in keys:
            assert await db.get(Setting, "internal.schedule_due." + key)


async def test_history_retry_does_not_repeat_completed_callback(database):
    path, factory = database
    calls = 0
    releases = []

    async def callback():
        nonlocal calls
        calls += 1
        releases.append(hold_write_lock(path))
        return {"completed": True}

    result = await tracked(factory, "provider_health", callback)
    await asyncio.gather(*releases)
    assert result == {"completed": True} and calls == 1
    async with factory() as db:
        runs = list(await db.scalars(select(ScheduleRun)))
        assert len(runs) == 1 and runs[0].status == "success"


async def test_heartbeat_retries_without_changing_attempt(database):
    path, factory = database
    async with factory() as db:
        await queue.enqueue(db, "process_message", {})
    claimed = await queue.claim(factory)
    assert claimed is not None
    async with factory() as db:
        before = (await db.get(Job, claimed.id)).locked_at
    release = hold_write_lock(path)
    await queue.heartbeat(factory, claimed)
    await release
    async with factory() as db:
        job = await db.get(Job, claimed.id)
        assert job.locked_at > before
        assert job.status == "running" and job.attempts == 1


async def test_history_retry_preserves_callback_failure(database):
    path, factory = database
    calls = 0
    releases = []

    async def callback():
        nonlocal calls
        calls += 1
        releases.append(hold_write_lock(path))
        raise ValueError("classification failed")

    with pytest.raises(ValueError, match="classification failed"):
        await tracked(factory, "provider_health", callback)
    await asyncio.gather(*releases)
    assert calls == 1
    async with factory() as db:
        runs = list(await db.scalars(select(ScheduleRun)))
        assert len(runs) == 1 and runs[0].status == "failed"


async def test_manual_schedule_retries_real_writer_lock(database):
    from app.api.operations import _run_now

    path, factory = database
    release = hold_write_lock(path)
    result = await _run_now(factory, "daily_summary")
    await release
    async with factory() as db:
        jobs = list(await db.scalars(select(Job)))
        assert len(jobs) == 1 and result["job_ids"] == [jobs[0].id]


async def test_dispatch_commits_before_processing_next_schedule(database, monkeypatch):
    from app import schedules

    path, factory = database
    original = schedules._dispatch_due
    visited = []

    async def dispatch(factory, key, now):
        if visited:
            async with factory() as db:
                jobs = list(await db.scalars(select(Job)))
                assert any(job.payload["schedule_key"] == visited[0] for job in jobs)
                db.add(Setting(key="internal.dispatch_probe." + key, value={}))
                await db.commit()
        await original(factory, key, now)
        visited.append(key)

    monkeypatch.setattr(schedules, "_dispatch_due", dispatch)
    await schedules.due_schedules(SimpleNamespace(session_factory=factory))
    assert len(visited) > 1
