import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.benchmark_learning import summarize
from app.classify.benchmark_learning import test_chat as in_test_split
from app.classify.learning import capture, compare, retrieve, select_examples
from app.classify.ollama import OllamaModerator
from app.classify.pipeline import run_pipeline
from app.classify.stages import StageContext
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.db.models import (
    Chat,
    Instance,
    LearningExample,
    LearningRun,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ReviewFeedback,
    SkippedGroup,
)
from app.settings_store import set_setting

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def test_hebrew_vowel_marks_do_not_split_tokens():
    from app.classify.learning import tokens

    assert tokens("שָׁלוֹם חֲבֵרִים") == tokens("שלום חברים")
    assert tokens("אני here מָחָר") == tokens("אני here מחר")


@pytest.fixture
async def db(tmp_path: Path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'learning.db'}"
    await asyncio.to_thread(upgrade_head, url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


async def samples(db: AsyncSession) -> tuple[Message, Message]:
    chat = Chat(wa_chat_id="g@g.us")
    child = Instance(
        kid_name="Child", openwa_base_url="http://wa", openwa_instance_id="1", webhook_token="token"
    )
    db.add_all([chat, child])
    await db.flush()
    messages = []
    for i, text in enumerate(("אני אהרוג אותך מחר", "אני אהרוג אותך עכשיו")):
        message = Message(
            chat_id=chat.id,
            wa_message_id=str(i),
            type="text",
            text=text,
            sent_at=T0 + timedelta(days=i),
            verdict="review",
            status="done",
        )
        db.add(message)
        await db.flush()
        db.add(MessageReceipt(message_id=message.id, instance_id=child.id))
        messages.append(message)
    db.add(ReviewFeedback(message_id=messages[0].id, verdict="harmful"))
    await capture(db, messages[0], "harmful")
    await db.commit()
    return messages[0], messages[1]


async def test_retrieval_is_bounded_and_does_not_retrieve_target_or_holdout_chat(db):
    source, target = await samples(db)
    found = await retrieve(db, target)
    assert [e["message_id"] for e in found] == [source.id]
    assert found[0]["verdict"] == "harmful"
    assert await retrieve(db, source) == []
    assert await retrieve(db, target, exclude_chats={source.chat_id}) == []


async def test_explicit_details_reach_examples_only_for_exact_reviewed_content(db):
    from app.classify.learning import content_hash

    source, target = await samples(db)
    feedback = await db.get(ReviewFeedback, source.id)
    feedback.content_hash = content_hash(source)
    feedback.categories = ["violence"]
    feedback.explanation = "איום ישיר"
    await db.commit()
    found = await retrieve(db, target)
    assert found[0]["human_categories"] == ["violence"]
    assert found[0]["human_explanation"] == "איום ישיר"
    feedback.content_hash = "stale"
    await db.commit()
    assert "human_explanation" not in (await retrieve(db, target))[0]


@pytest.mark.parametrize("change", ["edit", "redact", "revoke", "disable", "missing", "skip"])
async def test_invalid_sources_are_excluded_immediately(db, change):
    source, target = await samples(db)
    if change == "edit":
        source.text = "changed wording"
    elif change == "redact":
        source.redacted = True
    elif change == "revoke":
        source.revoked_at = T0
    elif change == "disable":
        (await db.get(LearningExample, source.id)).enabled = False
    elif change == "missing":
        db.add(ReviewDataIssue(message_id=source.id, issue="missing_data"))
    elif change == "skip":
        db.add(SkippedGroup(chat_id=source.chat_id, instance_id=1))
    await db.commit()
    assert await retrieve(db, target) == []


async def test_exact_child_scope_blocks_cross_child_and_shared_message_leaks(db):
    source, target = await samples(db)
    child = Instance(
        kid_name="Other", openwa_base_url="http://wa", openwa_instance_id="2", webhook_token="other"
    )
    db.add(child)
    await db.flush()
    db.add(MessageReceipt(message_id=source.id, instance_id=child.id))
    await db.commit()
    assert await retrieve(db, target) == []


@pytest.mark.parametrize("kind,verdict", [("image", "safe"), ("text", "ignored")])
async def test_media_and_ignore_never_become_examples(db, kind, verdict):
    _, target = await samples(db)
    target.type = kind
    await capture(db, target, verdict)
    await db.commit()
    assert await db.get(LearningExample, target.id) is None


async def test_source_deletion_cascades_example(db):
    source, _ = await samples(db)
    await db.execute(delete(Message).where(Message.id == source.id))
    await db.commit()
    assert await db.get(LearningExample, source.id) is None


async def test_contradictory_identical_examples_are_not_used(db):
    source, target = await samples(db)
    duplicate = Message(
        chat_id=source.chat_id,
        wa_message_id="duplicate",
        type="text",
        text=source.text,
        sent_at=T0 + timedelta(hours=1),
    )
    db.add(duplicate)
    await db.flush()
    db.add_all(
        [
            MessageReceipt(message_id=duplicate.id, instance_id=1),
            ReviewFeedback(message_id=duplicate.id, verdict="safe"),
        ]
    )
    await capture(db, duplicate, "safe")
    await db.commit()
    assert await retrieve(db, target) == []


def scores(violence: float) -> dict[str, float]:
    return {**dict.fromkeys(DEFAULT_THRESHOLDS, 0.0), "violence": violence}


def response(violence: float) -> httpx.Response:
    return httpx.Response(200, json={"message": {"content": json.dumps(scores(violence))}})


@pytest.mark.parametrize(
    "mode,expected", [("off", "safe"), ("shadow", "safe"), ("active", "harmful")]
)
@respx.mock
async def test_mode_controls_decision_and_shadow_stays_out_of_baseline_trace(db, mode, expected):
    source, target = await samples(db)
    await set_setting(db, "classification.learning_mode", mode)
    route = respx.post("http://ollama/api/chat").mock(side_effect=[response(0), response(0.99)])
    client = OllamaModerator("http://ollama", "model")
    ctx = StageContext(db, client, "model", dict(DEFAULT_THRESHOLDS), 8, timedelta(hours=6))
    try:
        baseline = await run_pipeline(target, ctx)
        outcome = await compare(target, ctx, baseline)
        await db.commit()
        assert outcome.verdict == expected
        if mode == "off":
            assert len(route.calls) == 1
            assert await db.scalar(select(LearningRun)) is None
        else:
            run = await db.scalar(select(LearningRun))
            assert run.example_ids == [source.id]
            assert run.baseline_verdict == "safe" and run.candidate_verdict == "harmful"
            payload = json.loads(route.calls[1].request.content)
            assert source.text in payload["messages"][1]["content"]
            assert payload["messages"][-1]["content"] == target.text
            assert len(outcome.results) == (1 if mode == "shadow" else 2)
            await db.execute(delete(Message).where(Message.id == target.id))
            await db.commit()
            assert await db.scalar(select(LearningRun)) is None
    finally:
        await client.aclose()


@respx.mock
async def test_active_never_clears_baseline_harm(db):
    _, target = await samples(db)
    await set_setting(db, "classification.learning_mode", "active")
    respx.post("http://ollama/api/chat").mock(side_effect=[response(0.99), response(0)])
    client = OllamaModerator("http://ollama", "model")
    ctx = StageContext(db, client, "model", dict(DEFAULT_THRESHOLDS), 8, timedelta(hours=6))
    try:
        outcome = await compare(target, ctx, await run_pipeline(target, ctx))
        assert outcome.verdict == "harmful"
        assert outcome.results[0].scores["violence"] == 0.99
    finally:
        await client.aclose()


@pytest.mark.parametrize("mode,expected", [("shadow", "safe"), ("active", "review")])
@respx.mock
async def test_candidate_failure_does_not_turn_into_safe_in_active(db, mode, expected):
    _, target = await samples(db)
    await set_setting(db, "classification.learning_mode", mode)
    respx.post("http://ollama/api/chat").mock(side_effect=[response(0), httpx.Response(503)])
    client = OllamaModerator("http://ollama", "model")
    ctx = StageContext(db, client, "model", dict(DEFAULT_THRESHOLDS), 8, timedelta(hours=6))
    try:
        outcome = await compare(target, ctx, await run_pipeline(target, ctx))
        assert outcome.verdict == expected
        await db.commit()
        run = await db.scalar(select(LearningRun))
        assert run.error == "TransientError" and run.candidate_verdict is None
    finally:
        await client.aclose()


async def test_parent_review_captures_and_admin_can_revoke_example(app_client: Any):
    async with app_client.app.state.session_factory() as db:
        _, target = await samples(db)
        mid = target.id
    result = await app_client.post(f"/api/review/{mid}", json={"resolution": "safe"})
    assert result.status_code == 200
    items = (await app_client.get("/api/learning/examples")).json()["items"]
    assert any(e["message_id"] == mid and e["verdict"] == "safe" for e in items)
    assert (
        await app_client.patch(f"/api/learning/examples/{mid}", json={"enabled": False})
    ).status_code == 200
    assert (await app_client.get("/api/learning/runs")).json()["summary"]["reviewed_messages"] == 0


async def test_import_skips_reviews_edited_after_decision(app_client: Any):
    async with app_client.app.state.session_factory() as db:
        _, target = await samples(db)
        db.add(ReviewFeedback(message_id=target.id, verdict="safe", reviewed_at=T0))
        target.edited_at = T0 + timedelta(days=2)
        await db.commit()
    result = await app_client.post("/api/learning/examples/import")
    assert result.status_code == 200 and result.json()["imported"] == 0


@pytest.mark.parametrize("mode,expected", [("shadow", "safe"), ("active", "harmful")])
@respx.mock
async def test_worker_persists_comparison_and_only_active_changes_alert_hook(
    app_client: Any,
    mode: str,
    expected: str,
):
    from app.db.models import Classification
    from app.jobs.handlers import Deps
    from app.jobs.queue import claim, enqueue
    from app.jobs.worker import run_one
    from app.providers import Providers

    result = await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "runtime.classification_provider": "ollama",
                "runtime.ollama_base_url": "http://ollama",
                "runtime.ollama_model": "model",
                "classification.learning_mode": mode,
            }
        },
    )
    assert result.status_code == 200
    factory = app_client.app.state.session_factory
    async with factory() as db:
        _, target = await samples(db)
        mid = target.id
        await enqueue(db, "process_message", {"message_id": mid})
    route = respx.post("http://ollama/api/chat").mock(side_effect=[response(0), response(0.99)])
    observed = []

    async def hook(_db, message, _outcome):
        observed.append(message.id)

    cfg = get_settings()
    deps = Deps(factory, Providers(), cfg.key_bytes, cfg.data_dir, on_harmful=hook)
    try:
        job = await claim(factory, types=("process_message",))
        assert job is not None and await run_one(job, deps) == "done"
        async with factory() as db:
            assert (await db.get(Message, mid)).verdict == expected
            assert (await db.scalar(select(LearningRun))).mode == mode
            stages = list(await db.scalars(select(Classification.stage)))
            assert stages == (
                ["moderation"] if mode == "shadow" else ["moderation", "learning_moderation"]
            )
        assert observed == ([] if mode == "shadow" else [mid])
        assert len(route.calls) == 2
    finally:
        await deps.providers.aclose()


def test_benchmark_split_stable_and_abstentions_visible():
    assert in_test_split("g@g.us") == in_test_split("g@g.us")
    result = summarize([{"human": "harmful", "candidate": "review"}], "candidate")
    assert result["confusion"]["harmful"]["review"] == 1
    assert result["harmful_detection_rate"] == 0 and result["precision"] is None


@pytest.mark.parametrize("target_text", ["You will not survive tomorrow", "💀🔪"])
@respx.mock
async def test_semantic_retrieval_finds_different_words_without_storing_vectors(db, target_text):
    source, target = await samples(db)
    target.text = target_text
    await db.commit()
    assert await retrieve(db, target, strategy="lexical") == []
    await set_setting(db, "classification.learning_embedding_model", "multilingual")
    route = respx.post("http://ollama/api/embed").mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [[2, 0], [4, 0]]},
        )
    )
    client = OllamaModerator("http://ollama", "model")
    try:
        selection = await select_examples(db, target, embedder=client, strategy="semantic")
        assert [e["message_id"] for e in selection.examples] == [source.id]
        assert selection.metadata["actual"] == "semantic"
        assert selection.metadata["embedding_model"] == "multilingual"
        payload = json.loads(route.calls[0].request.content)
        assert payload["input"] == [target.text, source.text] and payload["truncate"] is False
        assert not hasattr(await db.get(LearningExample, source.id), "embedding")
    finally:
        await client.aclose()


@respx.mock
async def test_semantic_filters_low_similarity_and_keeps_holdout_chats_out_of_embed_request(db):
    source, target = await samples(db)
    await set_setting(db, "classification.learning_embedding_model", "multilingual")
    route = respx.post("http://ollama/api/embed").mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [[1, 0], [0, 1]]},
        )
    )
    client = OllamaModerator("http://ollama", "model")
    try:
        assert (
            await select_examples(db, target, embedder=client, strategy="semantic")
        ).examples == []
        assert (
            await select_examples(
                db, target, embedder=client, strategy="semantic", exclude_chats={source.chat_id}
            )
        ).examples == []
        assert len(route.calls) == 1
        source.redacted = True
        await db.commit()
        assert (
            await select_examples(db, target, embedder=client, strategy="semantic")
        ).examples == []
        assert len(route.calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[1, 0]],
        [[1, 0], [True, 0]],
        [[1, 0], [0, 0]],
        [[1, 0], [1]],
        [[1, 0], [float("nan"), 0]],
        [None, [1, 0]],
    ],
)
@respx.mock
async def test_malformed_embeddings_fall_back_to_lexical(db, vectors):
    source, target = await samples(db)
    await set_setting(db, "classification.learning_embedding_model", "multilingual")
    respx.post("http://ollama/api/embed").mock(
        return_value=httpx.Response(
            200,
            content=json.dumps({"embeddings": vectors}),
        )
    )
    client = OllamaModerator("http://ollama", "model")
    try:
        selection = await select_examples(db, target, embedder=client, strategy="semantic")
        assert [e["message_id"] for e in selection.examples] == [source.id]
        assert selection.metadata["actual"] == "lexical"
        assert selection.metadata["fallback"] == "TransientError"
    finally:
        await client.aclose()


@respx.mock
async def test_semantic_never_embeds_cross_child_sources(db):
    source, target = await samples(db)
    child = Instance(
        kid_name="Other", openwa_base_url="http://wa", openwa_instance_id="2", webhook_token="other"
    )
    db.add(child)
    await db.flush()
    db.add(MessageReceipt(message_id=source.id, instance_id=child.id))
    await db.commit()
    await set_setting(db, "classification.learning_embedding_model", "multilingual")
    client = OllamaModerator("http://ollama", "model")
    try:
        selection = await select_examples(db, target, embedder=client, strategy="semantic")
        assert selection.examples == [] and selection.metadata["candidates"] == 0
        assert len(respx.calls) == 0
    finally:
        await client.aclose()


@respx.mock
async def test_semantic_fallback_without_matches_is_visible_and_does_not_change_active_decision(db):
    _, target = await samples(db)
    target.text = "Entirely different words"
    await db.commit()
    await set_setting(db, "classification.learning_mode", "active")
    await set_setting(db, "classification.learning_retrieval", "semantic")
    respx.post("http://ollama/api/chat").mock(return_value=response(0))
    client = OllamaModerator("http://ollama", "model")
    ctx = StageContext(db, client, "model", dict(DEFAULT_THRESHOLDS), 8, timedelta(hours=6))
    try:
        outcome = await compare(target, ctx, await run_pipeline(target, ctx))
        assert outcome.verdict == "safe"
        run = await db.scalar(select(LearningRun))
        assert run.error == "NoRelevantExamples"
        assert run.retrieval["fallback"] == "embedding_model_not_configured"
    finally:
        await client.aclose()


@respx.mock
async def test_embedding_connection_check_and_numeric_settings_validation(app_client: Any):
    respx.post("http://ollama/api/embed").mock(
        return_value=httpx.Response(
            200,
            json={"embeddings": [[1, 0], [0, 1]]},
        )
    )
    result = await app_client.post(
        "/api/settings/test/ollama_embedding",
        json={"base_url": "http://ollama", "model": "multilingual"},
    )
    assert result.status_code == 200 and result.json()["ok"] is True
    for value in [True, -0.1, 1.1, "0.7"]:
        result = await app_client.put(
            "/api/settings",
            json={
                "settings": {
                    "classification.learning_min_similarity": value,
                }
            },
        )
        assert result.status_code == 422


@respx.mock
async def test_benchmark_evaluates_same_targets_without_matches_and_makes_no_writes(db, capsys):
    from unittest.mock import patch

    from sqlalchemy import func

    from app.classify.benchmark_learning import evaluate

    source, target = await samples(db)
    chat = await db.get(Chat, source.chat_id)
    chat.wa_chat_id = next(f"test{i}@g.us" for i in range(100) if in_test_split(f"test{i}@g.us"))
    db.add(ReviewFeedback(message_id=target.id, verdict="safe"))
    await capture(db, target, "safe")
    await set_setting(db, "runtime.ollama_base_url", "http://ollama")
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(LearningExample))
    route = respx.post("http://ollama/api/chat").mock(return_value=response(0))
    cfg_url = str(db.bind.url)
    with patch(
        "app.classify.benchmark_learning.make_engine", side_effect=lambda: make_engine(cfg_url)
    ):
        await evaluate(30, "semantic")
    report = json.loads(capsys.readouterr().out)
    assert report["evaluated"] == 2 and report["retrieval_matches"] == 0
    assert report["baseline"] == report["candidate"]
    assert len(route.calls) == 2
    assert await db.scalar(select(func.count()).select_from(LearningExample)) == before
    assert await db.scalar(select(LearningRun)) is None
