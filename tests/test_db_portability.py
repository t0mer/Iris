from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import mysql, postgresql, sqlite

from app.db import search
from app.db.jsonq import json_array_contains
from app.db.models import Alert, Chat, Message
from app.jobs.queue import has_active_job

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_json_array_contains_compiles_for_each_database() -> None:
    expr = json_array_contains(Alert.categories, "violence")
    pg = str(expr.compile(dialect=postgresql.dialect()))
    my = str(expr.compile(dialect=mysql.dialect()))
    lite = str(expr.compile(dialect=sqlite.dialect()))
    assert "jsonb_exists(CAST(alerts.categories AS JSONB)" in pg
    assert "JSON_CONTAINS(alerts.categories, JSON_QUOTE(" in my
    assert "json_each(alerts.categories)" in lite


def test_job_payload_lookups_use_the_portable_json_api() -> None:
    from app.db.models import Job

    q = select(Job.id).where(Job.payload["message_id"].as_integer() == 3)
    for dialect in (postgresql.dialect(), mysql.dialect(), sqlite.dialect()):
        assert (
            "json_extract" not in str(q.compile(dialect=dialect)).lower()
            or dialect.name != "postgresql"
        )


async def _seed(app_client: Any) -> None:
    async with app_client.app.state.session_factory() as s:
        chat = Chat(wa_chat_id="c1", name="Class")
        s.add(chat)
        await s.flush()
        rows = [
            ("a", "Hello there, how ARE you", None, "Noa", False, 0),
            ("b", "שלום חבר, מה קורה", None, "Dan", False, 1),
            ("c", None, "voice transcript about football", "Eden", False, 2),
            ("d", "[redacted]", "[redacted]", "Hidden Person", True, 3),
            ("e", "100% sure_thing", None, "Noa", False, 4),
        ]
        for h, text, tr, sender, red, i in rows:
            s.add(
                Message(
                    wa_message_id=h,
                    chat_id=chat.id,
                    type="text",
                    text=text,
                    transcript=tr,
                    sender_name=sender,
                    redacted=red,
                    sent_at=NOW + timedelta(minutes=i),
                )
            )
        await s.commit()


async def _find(app_client: Any, q: str) -> dict[int, str]:
    async with app_client.app.state.session_factory() as s:
        return await search._substring(s, search.search_tokens(q))


async def test_substring_search_is_case_insensitive_and_matches_inside_words(
    app_client: Any,
) -> None:
    await _seed(app_client)
    hits = await _find(app_client, "are")
    assert len(hits) == 1 and "\x02ARE\x03" in next(iter(hits.values()))
    assert len(await _find(app_client, "foot")) == 1  # inside a word, in a transcript


async def test_substring_search_handles_hebrew_sender_and_all_words(app_client: Any) -> None:
    await _seed(app_client)
    assert len(await _find(app_client, "קורה")) == 1
    assert len(await _find(app_client, "שלום קורה")) == 1  # both words present
    assert await _find(app_client, "שלום football") == {}  # one word missing
    assert len(await _find(app_client, "noa")) == 2  # the sender's name counts


async def test_wildcards_in_the_query_are_literal_and_redacted_rows_never_match(
    app_client: Any,
) -> None:
    await _seed(app_client)
    assert await _find(app_client, "%") == {}  # punctuation-only has no tokens
    assert len(await _find(app_client, "sure_thing")) == 1
    assert await _find(app_client, "su_e") == {}  # the _ is not a single-character wildcard
    assert await _find(app_client, "Hidden") == {}  # redacted: not even the sender matches


async def test_substring_results_are_newest_first_with_a_trimmed_snippet(app_client: Any) -> None:
    await _seed(app_client)
    async with app_client.app.state.session_factory() as s:
        chat = (await s.execute(select(Chat))).scalar_one()
        s.add(
            Message(
                wa_message_id="long",
                chat_id=chat.id,
                type="text",
                text="x" * 200 + " needle " + "y" * 200,
                sender_name="Z",
                sent_at=NOW + timedelta(hours=1),
            )
        )
        await s.commit()
    hits = await _find(app_client, "needle")
    snippet = next(iter(hits.values()))
    assert snippet.startswith("…") and snippet.endswith("…") and len(snippet) < 160
    ids = list(await _find(app_client, "noa"))
    assert ids == sorted(ids, reverse=True)


async def test_search_dispatches_on_the_database(app_client: Any) -> None:
    await _seed(app_client)
    r = (await app_client.get("/api/messages", params={"q": "hello"})).json()
    assert r["total"] == 1 and "\x02" in r["items"][0]["snippet"]


async def test_has_active_job_uses_the_portable_lookup(app_client: Any) -> None:
    async with app_client.app.state.session_factory() as s:
        assert await has_active_job(s, 1) is False
