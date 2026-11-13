import asyncio
import sqlite3

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from app.db.engine import make_engine, make_session_factory
from app.db.models import Base, Instance, Job, Setting
from app.db.retry import retry_sqlite_busy
from app.jobs import queue
from app.jobs.handlers import Deps
from app.jobs.worker import run_one
from app.providers import Providers
from tests.test_webhooks import fx, make_instance, post


@pytest.mark.sqlite_only
@pytest.mark.parametrize("outcome", ["done", "failed", "queued", "deferred"])
async def test_busy_outcome_retries_write_without_repeating_handler(tmp_path, monkeypatch, outcome):
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'jobs.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def short_wait(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA busy_timeout=25")
        cursor.close()

    factory = make_session_factory(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Job(type="deliver_alert", payload={}, max_attempts=3))
        await db.commit()
    job = await queue.claim(factory)
    assert job is not None
    calls = 0
    retries = 0
    blocker = factory()

    async def handler(*_):
        nonlocal calls
        calls += 1
        blocker.add(Setting(key="internal.concurrent_write", value=True))
        await blocker.flush()
        if outcome == "failed":
            raise queue.PermanentError("Rejected")
        if outcome == "queued":
            raise queue.TransientError("Unavailable")
        if outcome == "deferred":
            raise queue.DeferredError("Quiet hours", 60)

    async def release_writer(_delay):
        nonlocal retries
        retries += 1
        await blocker.rollback()

    monkeypatch.setattr("app.db.retry.sleep", release_writer)
    deps = Deps(factory, Providers(), b"k" * 32)
    try:
        result = await run_one(job, deps, {"deliver_alert": handler})
        assert result == ("queued" if outcome == "deferred" else outcome)
        assert calls == retries == 1
        async with factory() as db:
            stored = await db.get(Job, job.id)
            assert stored.status == result
            assert stored.locked_at is None
            assert stored.attempts == (0 if outcome == "deferred" else 1)
    finally:
        await blocker.close()
        await deps.providers.aclose()
        await engine.dispose()


@pytest.mark.parametrize("code,expected", [(5, 4), (6, 4), (517, 4), (1, 1)])
async def test_persistent_or_unrelated_database_error_is_not_retried_forever(
    monkeypatch, code, expected
):
    calls = 0
    error = sqlite3.OperationalError("test error")
    error.sqlite_errorcode = code

    async def no_wait(_delay):
        pass

    monkeypatch.setattr("app.db.retry.sleep", no_wait)

    @retry_sqlite_busy
    async def write():
        nonlocal calls
        calls += 1
        raise OperationalError("UPDATE", {}, error)

    with pytest.raises(OperationalError):
        await write()
    assert calls == expected


@pytest.mark.sqlite_only
async def test_unsigned_webhook_waiting_for_ingestion_does_not_hold_writer(app_client, monkeypatch):
    from app.ingest import webhooks

    monkeypatch.setattr(webhooks, "_STORE_LOCK", asyncio.Lock())
    iid, token = await make_instance(app_client)
    factory = app_client.app.state.session_factory
    async with factory() as db:
        instance = await db.get(Instance, iid)
        instance.signature_required = False
        await db.commit()
    waiting = asyncio.Event()
    original_store = webhooks._store

    async def store(*args):
        waiting.set()
        return await original_store(*args)

    monkeypatch.setattr(webhooks, "_store", store)
    task = None
    try:
        async with webhooks._STORE_LOCK:
            task = asyncio.create_task(
                post(app_client, token, fx("text_received_mixed"), sign=False)
            )
            await asyncio.wait_for(waiting.wait(), 2)
            # The lock owner must be free to finish its own database transaction.
            async with factory() as db:
                await db.execute(text("PRAGMA busy_timeout=25"))
                db.add(Setting(key="internal.concurrent_ingestion", value=True))
                await db.commit()
        assert (await task).json() == {"result": "accepted"}
        async with factory() as db:
            assert (await db.get(Instance, iid)).last_webhook_at is not None
    finally:
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
