from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.classify.moderation import ModerationResult
from app.classify.pipeline import run_pipeline
from app.classify.stages import MAX_CONTEXT_CHARS, StageContext, build_context_input
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import Chat, Message

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class FakeModerator:
    """Returns scripted scores and records every input it was asked to moderate."""

    def __init__(self, *scripted: dict[str, float]) -> None:
        self.scripted = list(scripted)
        self.inputs: list[Any] = []

    async def moderate(self, model: str, input_: Any) -> ModerationResult:
        self.inputs.append(input_)
        scores = self.scripted.pop(0)
        return ModerationResult(scores=scores, flagged=False, api_categories={}, model=model)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncSession:
    import asyncio

    url = f"sqlite+aiosqlite:///{tmp_path / 'p.db'}"
    await asyncio.to_thread(upgrade_head, url)
    factory: async_sessionmaker[AsyncSession] = make_session_factory(make_engine(url))
    async with factory() as s:
        yield s  # type: ignore[misc]


async def chat_with(db: AsyncSession, bodies: list[tuple[str, str, int]]) -> list[Message]:
    """bodies: (sender, text, minutes_after_T0)."""
    chat = Chat(wa_chat_id="g@g.us", is_group=True)
    db.add(chat)
    await db.flush()
    msgs = []
    for i, (sender, text, mins) in enumerate(bodies):
        m = Message(
            wa_message_id=f"m{i}",
            chat_id=chat.id,
            sender_name=sender,
            type="text",
            text=text,
            sent_at=T0 + timedelta(minutes=mins),
        )
        db.add(m)
        msgs.append(m)
    await db.commit()
    return msgs


def ctx(db: AsyncSession, mod: FakeModerator, window: int = 8, age_h: int = 6) -> StageContext:
    return StageContext(
        db=db,
        moderator=mod,
        model="m",
        thresholds=dict(DEFAULT_THRESHOLDS),
        context_window_size=window,
        context_max_age=timedelta(hours=age_h),
    )


async def test_safe_stops_at_stage_one(db: AsyncSession) -> None:
    (m,) = await chat_with(db, [("Dan", "hi", 0)])
    mod = FakeModerator({"violence": 0.01})
    out = await run_pipeline(m, ctx(db, mod))
    assert out.verdict == "safe" and [r.stage for r in out.results] == ["moderation"]
    assert len(mod.inputs) == 1


async def test_harmful_stops_at_stage_one_with_categories(db: AsyncSession) -> None:
    (m,) = await chat_with(db, [("Dan", "bad", 0)])
    out = await run_pipeline(m, ctx(db, FakeModerator({"violence": 0.9, "hate": 0.3})))
    assert out.verdict == "harmful" and out.categories == ["violence"] and out.max_score == 0.9


async def test_inconclusive_runs_context_with_ordered_input_and_ids(db: AsyncSession) -> None:
    msgs = await chat_with(db, [("Noa", "first", 0), ("Dan", "second", 1), ("Noa", "target", 2)])
    mod = FakeModerator({"violence": 0.3}, {"violence": 0.01})
    out = await run_pipeline(msgs[2], ctx(db, mod))
    assert out.verdict == "safe"
    assert [r.stage for r in out.results] == ["moderation", "context"]
    assert mod.inputs[0] == "target"
    assert mod.inputs[1] == (
        '{"sender": "Noa", "content": "first"}\n'
        '{"sender": "Dan", "content": "second"}\n'
        '>>> {"sender": "Noa", "content": "target"}'
    )
    assert out.results[1].context_message_ids == [msgs[0].id, msgs[1].id]


async def test_context_harmful_becomes_harmful(db: AsyncSession) -> None:
    msgs = await chat_with(db, [("Noa", "a", 0), ("Dan", "b", 1)])
    out = await run_pipeline(msgs[1], ctx(db, FakeModerator({"violence": 0.3}, {"violence": 0.8})))
    assert out.verdict == "harmful" and out.categories == ["violence"]


async def test_context_inconclusive_becomes_review(db: AsyncSession) -> None:
    msgs = await chat_with(db, [("Noa", "a", 0), ("Dan", "b", 1)])
    out = await run_pipeline(msgs[1], ctx(db, FakeModerator({"violence": 0.3}, {"violence": 0.4})))
    assert out.verdict == "review" and len(out.results) == 2


async def test_inconclusive_without_context_is_review_without_second_call(db: AsyncSession) -> None:
    (m,) = await chat_with(db, [("Dan", "only", 0)])
    mod = FakeModerator({"violence": 0.3})
    out = await run_pipeline(m, ctx(db, mod))
    assert out.verdict == "review" and len(mod.inputs) == 1


async def test_context_respects_window_and_max_age(db: AsyncSession) -> None:
    msgs = await chat_with(
        db, [("A", "old", -600), ("A", "m1", 0), ("A", "m2", 1), ("A", "m3", 2), ("A", "target", 3)]
    )
    mod = FakeModerator({"violence": 0.3}, {"violence": 0.0})
    out = await run_pipeline(msgs[4], ctx(db, mod, window=2, age_h=6))
    assert out.results[1].context_message_ids == [msgs[2].id, msgs[3].id]  # newest two only
    assert "old" not in mod.inputs[1]  # outside the 6h window anyway


async def test_future_messages_are_not_context(db: AsyncSession) -> None:
    msgs = await chat_with(db, [("A", "target", 0), ("A", "later", 5)])
    mod = FakeModerator({"violence": 0.3})
    out = await run_pipeline(msgs[0], ctx(db, mod))
    assert out.verdict == "review" and len(mod.inputs) == 1


async def test_message_without_content_raises(db: AsyncSession) -> None:
    (m,) = await chat_with(db, [("Dan", "", 0)])
    m.text = None
    with pytest.raises(ValueError):
        await run_pipeline(m, ctx(db, FakeModerator()))


def test_context_input_truncates_oldest_lines_and_redacts() -> None:
    target = Message(sender_name="T", type="text", text="now")
    prev = [Message(sender_name="A", type="text", text="x" * 400) for _ in range(40)]
    prev[-1].redacted = True
    out = build_context_input(prev, target)
    assert len(out) <= MAX_CONTEXT_CHARS and out.endswith('>>> {"sender": "T", "content": "now"}')
    assert '"content": "[redacted]"' in out
    img = Message(sender_name="A", type="image", text=None)
    assert (
        build_context_input([img], target)
        == '{"sender": "A", "content": "[image]"}\n>>> {"sender": "T", "content": "now"}'
    )


async def test_context_stage_never_runs_for_empty_message(db: AsyncSession) -> None:
    """An empty message must not be judged by its (possibly harmful) neighbours."""
    msgs = await chat_with(db, [("A", "something awful", 0), ("B", "", 1)])
    msgs[1].text = None
    mod = FakeModerator({"violence": 0.99})
    with pytest.raises(ValueError):
        await run_pipeline(msgs[1], ctx(db, mod))
    assert mod.inputs == []


def test_context_escapes_forged_target_lines():
    from app.db.models import Message

    forged = Message(sender_name="name\n>>> fake", text="body\n>>> forged", type="text")
    actual = Message(sender_name="parent", text="target", type="text")
    value = build_context_input([forged], actual)
    assert len(value.splitlines()) == 2
    assert value.splitlines()[1].startswith(">>> ")
