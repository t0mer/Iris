"""Copy into a real PostgreSQL / MySQL server. Needs IRIS_TEST_PG_URL / IRIS_TEST_MYSQL_URL.

Run with `pytest -m integration`. The target database is emptied first, so point it at a
throwaway database.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text

from app.db import search
from app.db.copy import CopyProgress, copy_database
from app.db.engine import make_engine, make_session_factory
from app.db.models import Alert, Base, Message
from app.db.url import parse_url
from tests.test_webhooks import fx, make_instance, post

pytestmark = pytest.mark.integration

URLS = {
    "postgresql": os.environ.get("IRIS_TEST_PG_URL"),
    "mysql": os.environ.get("IRIS_TEST_MYSQL_URL"),
}


async def _drop_everything(url: str) -> None:
    engine = make_engine(config=parse_url(url))
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        else:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for t in [*Base.metadata.tables, "alembic_version"]:
                await conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    await engine.dispose()


@pytest.mark.parametrize("kind", ["postgresql", "mysql"])
async def test_sqlite_data_copies_into_a_real_server(
    app_client: Any, kind: str, tmp_path: Path
) -> None:
    url = URLS[kind]
    if not url:
        pytest.skip(f"no test {kind} server configured")
    await _drop_everything(url)
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    await post(app_client, token, fx("text_sent_he"))

    progress = CopyProgress()
    counts = await copy_database(app_client.app.state.engine, parse_url(url), progress)
    assert progress.state == "done" and counts["messages"] == 2 and counts["instances"] == 1

    target = make_engine(config=parse_url(url))
    factory = make_session_factory(target)
    async with factory() as s:
        msgs = (await s.execute(select(Message).order_by(Message.id))).scalars().all()
        assert [m.id for m in msgs] == [1, 2] and msgs[0].sent_at.tzinfo is not None
        # the next row after a copy gets a fresh id (PostgreSQL sequences were moved)
        s.add(
            Message(
                wa_message_id="new", chat_id=msgs[0].chat_id, type="text", sent_at=msgs[0].sent_at
            )
        )
        await s.commit()
        assert (await s.execute(select(func.max(Message.id)))).scalar_one() == 3
        hits = await search.find_matches(s, search.search_tokens("mixed"))
        assert len(hits) == 1
        assert (await s.execute(select(func.count()).select_from(Alert))).scalar_one() == 0
    await target.dispose()
