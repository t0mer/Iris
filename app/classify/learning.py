"""Bounded local retrieval of reviewed text examples; optional shadow/active comparison."""

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.ollama import OllamaModerator
from app.classify.pipeline import PipelineOutcome, run_pipeline
from app.classify.stages import StageContext, message_body
from app.db.models import (
    LearningExample,
    LearningRun,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ReviewFeedback,
    SkippedGroup,
)
from app.jobs.queue import PermanentError, TransientError
from app.settings_store import get_setting

MAX_EXAMPLE_CHARS = 1200
MAX_CANDIDATES = 200
MAX_EXAMPLES = 4
RETRIEVAL_VERSION = "lexical-v2"
SEMANTIC_VERSION = "semantic-v1"
TEXT_TYPES = {"text", "chat"}


def content_hash(message: Message) -> str:
    return hashlib.sha256(message_body(message).encode()).hexdigest()


def tokens(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    # Niqqud/cantillation must not split a Hebrew word into unrelated tokens.
    text = "".join(
        c
        for c in text
        if not ("\u0591" <= c <= "\u05bd" or c in "\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7")
    )
    return set(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def eligible(message: Message) -> bool:
    body = message_body(message)
    return bool(
        message.type in TEXT_TYPES
        and not message.redacted
        and message.revoked_at is None
        and body
        and len(body) <= MAX_EXAMPLE_CHARS
    )


async def capture(db: AsyncSession, message: Message, verdict: str) -> None:
    """Only an accepted human decision creates an example; AI output is never a label."""
    if verdict not in {"safe", "harmful"} or not eligible(message):
        return
    if await db.get(ReviewDataIssue, message.id) is not None:
        return
    if await db.get(LearningExample, message.id) is None:
        db.add(
            LearningExample(
                message_id=message.id,
                content_hash=content_hash(message),
                verdict=verdict,
            )
        )


@dataclass
class Selection:
    examples: list[dict[str, Any]]
    metadata: dict[str, Any]


async def select_examples(
    db: AsyncSession,
    target: Message,
    *,
    exclude_chats: set[int] | None = None,
    embedder: OllamaModerator | None = None,
    strategy: str | None = None,
) -> Selection:
    """Only earlier, unchanged examples belonging to exactly the same monitored children."""
    strategy = strategy or str(await get_setting(db, "classification.learning_retrieval"))
    metadata: dict[str, Any] = {
        "requested": strategy,
        "actual": "lexical",
        "version": RETRIEVAL_VERSION,
        "embedding_model": None,
        "fallback": None,
        "candidates": 0,
        "latency_ms": 0,
    }
    if not eligible(target):
        return Selection([], metadata)
    query_tokens = tokens(message_body(target))
    if not query_tokens and strategy != "semantic":
        return Selection([], metadata)
    children = set(
        await db.scalars(
            select(MessageReceipt.instance_id).where(MessageReceipt.message_id == target.id)
        )
    )
    if not children:
        return Selection([], metadata)
    statement = (
        select(LearningExample, Message)
        .join(Message, Message.id == LearningExample.message_id)
        .join(ReviewFeedback, ReviewFeedback.message_id == Message.id)
        .where(
            LearningExample.enabled.is_(True),
            LearningExample.verdict.in_(("safe", "harmful")),
            LearningExample.verdict == ReviewFeedback.verdict,
            Message.id != target.id,
            Message.redacted.is_(False),
            Message.revoked_at.is_(None),
            Message.type.in_(TEXT_TYPES),
            Message.sent_at < target.sent_at,
            Message.id.in_(
                select(MessageReceipt.message_id).where(
                    MessageReceipt.instance_id.in_(children),
                )
            ),
            ~select(ReviewDataIssue.message_id)
            .where(ReviewDataIssue.message_id == Message.id)
            .exists(),
            ~select(SkippedGroup.chat_id)
            .where(SkippedGroup.chat_id == Message.chat_id, SkippedGroup.instance_id.in_(children))
            .exists(),
        )
        .order_by(LearningExample.created_at.desc(), Message.id.desc())
        .limit(MAX_CANDIDATES)
    )
    if exclude_chats:
        statement = statement.where(Message.chat_id.not_in(exclude_chats))
    rows = list((await db.execute(statement)).all())
    ids = [message.id for _, message in rows]
    receipts: dict[int, set[int]] = {}
    for mid, iid in await db.execute(
        select(
            MessageReceipt.message_id,
            MessageReceipt.instance_id,
        ).where(MessageReceipt.message_id.in_(ids))
    ):
        receipts.setdefault(mid, set()).add(iid)
    candidates = []
    for example, message in rows:
        if receipts.get(message.id) != children or not eligible(message):
            continue
        if content_hash(message) != example.content_hash:
            continue
        candidates.append((example, message))
    metadata["candidates"] = len(candidates)
    started = time.perf_counter()
    similarities = None
    if strategy == "semantic" and candidates:
        embedding_model = await get_setting(db, "classification.learning_embedding_model")
        metadata["embedding_model"] = embedding_model
        if not embedding_model:
            metadata["fallback"] = "embedding_model_not_configured"
        elif embedder is None:
            metadata["fallback"] = "embedding_client_unavailable"
        else:
            try:
                vectors = await embedder.embed(
                    str(embedding_model),
                    [
                        message_body(target),
                        *[message_body(m) for _, m in candidates],
                    ],
                )
                similarities = [
                    max(
                        -1.0,
                        min(
                            1.0,
                            sum(
                                (a * b for a, b in zip(vectors[0], v, strict=True)),
                            ),
                        ),
                    )
                    for v in vectors[1:]
                ]
                metadata.update(
                    actual="semantic",
                    version=SEMANTIC_VERSION,
                    min_similarity=await get_setting(db, "classification.learning_min_similarity"),
                )
            except (PermanentError, TransientError) as exc:
                metadata["fallback"] = type(exc).__name__
    ranked = []
    labels_by_hash: dict[str, set[str]] = {}
    for index, (example, message) in enumerate(candidates):
        labels_by_hash.setdefault(example.content_hash, set()).add(example.verdict)
        if similarities is not None:
            similarity = similarities[index]
            if similarity < metadata["min_similarity"]:
                continue
        else:
            if not query_tokens:
                continue
            words = tokens(message_body(message))
            overlap = query_tokens & words
            similarity = len(overlap) / len(query_tokens | words)
            if similarity < 0.2 or len(overlap) < min(2, len(query_tokens)):
                continue
        ranked.append((similarity, message.id, example, message))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for similarity, _, example, message in ranked:
        if example.content_hash in seen or len(labels_by_hash[example.content_hash]) > 1:
            continue
        seen.add(example.content_hash)
        result.append(
            {
                "message_id": message.id,
                "content": message_body(message),
                "verdict": example.verdict,
                "similarity": round(similarity, 4),
            }
        )
        feedback = await db.get(ReviewFeedback, message.id)
        if feedback and feedback.content_hash == example.content_hash:
            result[-1]["human_categories"] = feedback.categories or []
            result[-1]["human_explanation"] = feedback.explanation
        if len(result) == MAX_EXAMPLES:
            break
    metadata["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return Selection(result, metadata)


async def retrieve(
    db: AsyncSession,
    target: Message,
    *,
    exclude_chats: set[int] | None = None,
    embedder: OllamaModerator | None = None,
    strategy: str | None = None,
) -> list[dict[str, Any]]:
    return (
        await select_examples(
            db,
            target,
            exclude_chats=exclude_chats,
            embedder=embedder,
            strategy=strategy,
        )
    ).examples


async def compare(
    message: Message,
    ctx: StageContext,
    baseline: PipelineOutcome,
) -> PipelineOutcome:
    mode = str(await get_setting(ctx.db, "classification.learning_mode"))
    if mode == "off" or not isinstance(ctx.moderator, OllamaModerator):
        return baseline
    selection = await select_examples(ctx.db, message, embedder=ctx.moderator)
    examples = selection.examples
    if not examples and not selection.metadata["fallback"]:
        return baseline
    started = time.perf_counter()
    candidate = None
    error = None
    if examples:
        try:
            candidate = await run_pipeline(message, replace(ctx, learning_examples=examples))
        except (PermanentError, TransientError) as exc:
            # Store only the error type: provider errors may contain private content.
            error = type(exc).__name__
    else:
        error = "NoRelevantExamples"
    ctx.db.add(
        LearningRun(
            message_id=message.id,
            mode=mode,
            model=ctx.model,
            content_hash=content_hash(message),
            retrieval_version=selection.metadata["version"],
            retrieval=selection.metadata,
            baseline_verdict=baseline.verdict,
            candidate_verdict=candidate.verdict if candidate else None,
            example_ids=[e["message_id"] for e in examples],
            baseline_scores=baseline.results[-1].scores,
            candidate_scores=candidate.results[-1].scores if candidate else None,
            thresholds={k: list(v) for k, v in ctx.thresholds.items()},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
        )
    )
    await ctx.db.flush()
    retained = list(
        await ctx.db.scalars(
            select(LearningRun.id)
            .where(LearningRun.message_id == message.id)
            .order_by(LearningRun.id.desc())
            .limit(10),
        )
    )
    await ctx.db.execute(
        delete(LearningRun).where(
            LearningRun.message_id == message.id,
            LearningRun.id.not_in(retained),
        )
    )
    if mode == "active":
        if not examples:
            return baseline
        if candidate is None:
            # An unavailable learning pass cannot clear a borderline message.
            if baseline.verdict != "harmful":
                baseline.verdict = "review"
            return baseline
        # Preserve stronger baseline evidence, including redaction-triggering categories.
        rank = {"safe": 0, "review": 1, "harmful": 2}
        if rank[baseline.verdict] > rank[candidate.verdict]:
            return baseline
        for result in candidate.results:
            result.stage = "learning_" + result.stage
        candidate.results = [*baseline.results, *candidate.results]
        return candidate
    return baseline
