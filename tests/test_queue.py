from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Job
from app.jobs import queue


@pytest.fixture
async def factory(tmp_path: Path) -> async_sessionmaker[AsyncSession]:
    import asyncio

    url = f"sqlite+aiosqlite:///{tmp_path / 'q.db'}"
    await asyncio.to_thread(upgrade_head, url)
    return make_session_factory(make_engine(url))


async def _job(f: async_sessionmaker[AsyncSession], **payload: object) -> int:
    async with f() as db:
        return await queue.enqueue(db, "process_message", dict(payload) or {"x": 1})


async def _status(f: async_sessionmaker[AsyncSession], jid: int) -> Job:
    async with f() as db:
        j = await db.get(Job, jid)
        assert j
        return j


async def test_claim_ack_in_order_and_empty(factory: async_sessionmaker[AsyncSession]) -> None:
    a, b = await _job(factory), await _job(factory)
    c1 = await queue.claim(factory)
    assert c1 and c1.id == a and c1.attempts == 1
    c2 = await queue.claim(factory)
    assert c2 and c2.id == b
    assert await queue.claim(factory) is None
    await queue.ack(factory, a)
    assert (await _status(factory, a)).status == "done"


async def test_transient_failure_backoff_schedule_and_dead_letter(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    jid = await _job(factory)
    expected = [5, 30, 120, 600]
    for n, secs in enumerate(expected, start=1):
        async with factory() as db:
            await db.execute(
                update(Job).where(Job.id == jid).values(run_after=datetime(2000, 1, 1))
            )
            await db.commit()
        job = await queue.claim(factory)
        assert job and job.attempts == n
        assert await queue.fail(factory, job, "boom", transient=True) == "queued"
        j = await _status(factory, jid)
        delay = (j.run_after - datetime.now(UTC)).total_seconds()
        assert secs - 2 < delay <= secs
        assert await queue.claim(factory) is None  # not eligible until run_after
    async with factory() as db:
        await db.execute(update(Job).where(Job.id == jid).values(run_after=datetime(2000, 1, 1)))
        await db.commit()
    last = await queue.claim(factory)
    assert last and last.attempts == 5
    assert await queue.fail(factory, last, "boom", transient=True) == "dead"
    assert (await _status(factory, jid)).status == "dead"


async def test_retry_after_overrides_short_backoff() -> None:
    assert queue.backoff_for(1, retry_after=90) == timedelta(seconds=90)
    assert queue.backoff_for(1, retry_after=1) == timedelta(seconds=5)


async def test_permanent_failure_is_immediate(factory: async_sessionmaker[AsyncSession]) -> None:
    jid = await _job(factory)
    job = await queue.claim(factory)
    assert job and await queue.fail(factory, job, "bad input", transient=False) == "failed"
    assert (await _status(factory, jid)).last_error == "bad input"


async def test_stale_lock_recovery(factory: async_sessionmaker[AsyncSession]) -> None:
    fresh, stale = await _job(factory), await _job(factory)
    await queue.claim(factory)
    await queue.claim(factory)
    async with factory() as db:
        await db.execute(
            update(Job)
            .where(Job.id == stale)
            .values(locked_at=(datetime.now(UTC) - timedelta(minutes=11)).replace(tzinfo=None))
        )
        await db.commit()
    assert await queue.recover_stale(factory) == 1
    assert (await _status(factory, stale)).status == "queued"
    assert (await _status(factory, fresh)).status == "running"


async def test_manual_retry_of_dead_job(factory: async_sessionmaker[AsyncSession]) -> None:
    jid = await _job(factory)
    job = await queue.claim(factory)
    assert job
    await queue.fail(factory, job, "x", transient=False)
    async with factory() as db:
        assert await queue.retry_job(db, jid) is True
        assert await queue.retry_job(db, jid) is False  # now queued, not retryable again
        assert (await db.execute(select(Job.status).where(Job.id == jid))).scalar_one() == "queued"


async def test_stale_job_out_of_attempts_is_dead_lettered(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    jid = await _job(factory)
    async with factory() as db:
        await db.execute(
            update(Job)
            .where(Job.id == jid)
            .values(
                status="running",
                attempts=5,
                locked_at=(datetime.now(UTC) - timedelta(minutes=30)).replace(tzinfo=None),
            )
        )
        await db.commit()
    assert await queue.recover_stale(factory) == 1
    j = await _status(factory, jid)
    assert j.status == "dead" and j.last_error


def test_backoff_clamps_hostile_retry_after() -> None:
    assert queue.backoff_for(1, retry_after=10**12) == timedelta(seconds=3600)
    assert queue.backoff_for(0) == timedelta(seconds=5)  # attempt 0 must not index backwards


async def test_has_active_job_blocks_duplicate_retry(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as db:
        dead = await queue.enqueue(db, "process_message", {"message_id": 7})
        await db.execute(update(Job).where(Job.id == dead).values(status="dead"))
        await db.commit()
        assert not await queue.has_active_job(db, 7)
        await queue.enqueue(db, "process_message", {"message_id": 7})
        assert await queue.has_active_job(db, 7) and not await queue.has_active_job(db, 8)
        assert await queue.retry_job(db, dead) is False  # a queued job for message 7 exists
