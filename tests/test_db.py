from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Chat, Message


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    await __import__("asyncio").to_thread(upgrade_head, url)
    return make_engine(url)


async def _insert(engine: AsyncEngine, body: str) -> int:

    async with make_session_factory(engine)() as s:
        chat = Chat(wa_chat_id="c1", name="g")
        s.add(chat)
        await s.flush()
        m = Message(
            wa_message_id="m1",
            chat_id=chat.id,
            type="text",
            text=body,
            sent_at=datetime.now(UTC),
        )
        s.add(m)
        await s.commit()
        return m.id


async def _hits(engine: AsyncEngine, q: str) -> int:
    async with engine.connect() as c:
        r = await c.execute(
            text("SELECT count(*) FROM messages_fts WHERE messages_fts MATCH :q"), {"q": q}
        )
        return int(r.scalar_one())


async def test_wal_enabled(engine: AsyncEngine) -> None:
    async with engine.connect() as c:
        assert (await c.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"


async def test_fts_hebrew_search_and_redaction(engine: AsyncEngine) -> None:
    mid = await _insert(engine, "שלום עולם hello")
    assert await _hits(engine, "שלום") == 1
    assert await _hits(engine, "hello") == 1
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE messages SET text='[redacted]', redacted=1 WHERE id=:i"), {"i": mid}
        )
    assert await _hits(engine, "שלום") == 0
    assert await _hits(engine, "redacted") == 0


async def test_redacted_insert_not_indexed_and_delete_keeps_index_sound(
    engine: AsyncEngine,
) -> None:
    async with engine.begin() as c:
        await c.execute(
            text(
                "INSERT INTO chats(id, wa_chat_id, is_group, updated_at) VALUES (9,'c9',0,'2026-01-01')"
            )
        )
        await c.execute(
            text(
                "INSERT INTO messages(id, wa_message_id, chat_id, type, text, from_me, redacted, status, sent_at, received_at)"
                " VALUES (50,'r',9,'text','secretword',0,1,'done','2026-01-01','2026-01-01')"
            )
        )
    assert await _hits(engine, "secretword") == 0
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM messages WHERE id=50"))
    async with engine.connect() as c:
        await c.execute(text("INSERT INTO messages_fts(messages_fts) VALUES ('integrity-check')"))


async def test_message_change_migration_round_trips(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    url = f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"
    await __import__("asyncio").to_thread(upgrade_head, url)
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = url
    await __import__("asyncio").to_thread(command.downgrade, cfg, "0003")
    await __import__("asyncio").to_thread(command.upgrade, cfg, "head")
    engine = make_engine(url)
    async with engine.connect() as c:
        tables = {r[0] for r in await c.execute(text("select name from sqlite_master"))}
        cols = {r[1] for r in await c.execute(text("pragma table_info(messages)"))}
    assert "message_revisions" in tables and {"edited_at", "revoked_at"} <= cols
