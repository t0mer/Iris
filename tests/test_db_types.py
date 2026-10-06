from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Chat, Job, Message
from app.db.types import UTCDateTime

NOW = datetime(2026, 10, 7, 12, 30, 15, 123456, tzinfo=UTC)


def test_column_type_per_dialect() -> None:
    t = UTCDateTime()
    assert t.compile(dialect=postgresql.dialect()) == "TIMESTAMP WITHOUT TIME ZONE"
    assert t.compile(dialect=mysql.dialect()) == "DATETIME(6)"
    assert t.compile(dialect=sqlite.dialect()) == "DATETIME"
    assert "WITH TIME ZONE" not in str(
        CreateTable(Message.__table__).compile(dialect=postgresql.dialect())
    )


def test_binding_converts_to_naive_utc_and_reading_returns_aware() -> None:
    t = UTCDateTime()
    d = sqlite.dialect()
    plus3 = NOW.astimezone(timezone(timedelta(hours=3)))
    assert t.process_bind_param(plus3, d) == NOW.replace(tzinfo=None)
    assert t.process_bind_param(NOW.replace(tzinfo=None), d) == NOW.replace(
        tzinfo=None
    )  # naive = UTC
    assert t.process_bind_param(None, d) is None
    assert t.process_result_value(NOW.replace(tzinfo=None), d) == NOW
    assert t.process_result_value(None, d) is None


async def test_round_trip_and_comparisons_on_sqlite(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    await __import__("asyncio").to_thread(upgrade_head, url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    async with factory() as s:
        chat = Chat(wa_chat_id="c", name="n")
        s.add(chat)
        await s.flush()
        s.add(Message(wa_message_id="m", chat_id=chat.id, type="text", sent_at=NOW))
        s.add(Job(type="x", payload={}, run_after=NOW))
        await s.commit()
    async with factory() as s:
        from sqlalchemy import select

        m = (await s.execute(select(Message))).scalar_one()
        assert m.sent_at == NOW and m.sent_at.tzinfo is not None
        # a naive and an aware bound value compare the same way
        later = (await s.execute(select(Job).where(Job.run_after <= NOW))).all()
        naive = (
            await s.execute(select(Job).where(Job.run_after <= NOW.replace(tzinfo=None)))
        ).all()
        assert len(later) == len(naive) == 1
    await engine.dispose()


async def test_strings_stored_by_older_versions_still_read_as_utc(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'old.db'}"
    await __import__("asyncio").to_thread(upgrade_head, url)
    engine = make_engine(url)
    async with engine.begin() as c:
        await c.execute(
            text(
                "INSERT INTO jobs (type, payload, status, attempts, max_attempts, run_after, "
                "created_at) VALUES ('x', '{}', 'queued', 0, 5, '2026-10-07 12:30:15.123456', "
                "'2026-10-07 12:30:15.000000')"
            )
        )
    factory = make_session_factory(engine)
    async with factory() as s:
        from sqlalchemy import select

        j = (await s.execute(select(Job))).scalar_one()
        assert j.run_after == NOW
    await engine.dispose()
