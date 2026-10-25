"""Read-only evaluation. Run: python -m app.classify.benchmark_learning --limit 30."""

import argparse
import asyncio
import hashlib
import json
import re
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.classify.evaluation_state import configuration_fingerprint, fingerprint
from app.classify.learning import content_hash, eligible, select_examples
from app.classify.ollama import OllamaModerator
from app.classify.pipeline import run_pipeline
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY
from app.classify.stages import StageContext, context_messages, message_body
from app.classify.thresholds import effective_thresholds
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.models import (
    Chat,
    LearningExample,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ReviewFeedback,
    SkippedGroup,
)
from app.jobs.queue import PermanentError, TransientError
from app.settings_store import get_setting, reload_runtime_settings


def test_chat(wa_chat_id: str) -> bool:
    return int(hashlib.sha256(wa_chat_id.encode()).hexdigest(), 16) % 5 == 0


def summarize(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    matrix = {
        actual: dict.fromkeys(("safe", "harmful", "review"), 0) for actual in ("safe", "harmful")
    }
    for row in rows:
        matrix[row["human"]][row[field]] += 1
    tp, fp = matrix["harmful"]["harmful"], matrix["safe"]["harmful"]
    harmful = sum(matrix["harmful"].values())
    return {
        "confusion": matrix,
        "precision": tp / (tp + fp) if tp + fp else None,
        "harmful_detection_rate": tp / harmful if harmful else None,
    }


def source_signature(message: Message) -> list[Any]:
    return [
        message.id,
        message.chat_id,
        content_hash(message),
        message.type,
        message.sent_at,
        message.edited_at,
        message.revoked_at,
        message.redacted,
    ]


async def evaluate(
    limit: int,
    strategy: str | None = None,
    *,
    emit: bool = True,
    checkpoint: dict[str, Any] | None = None,
    request_timeout: float = 30,
) -> dict[str, Any]:
    engine = make_engine()
    factory = make_session_factory(engine)
    client = None
    try:
        async with factory() as db:
            await reload_runtime_settings(db)
            cfg = get_settings()
            client = OllamaModerator(
                cfg.ollama_base_url,
                cfg.ollama_model,
                context_tokens=cfg.ollama_context_tokens,
                output_tokens=cfg.ollama_output_tokens,
            )
            chats = list((await db.execute(select(Chat.id, Chat.wa_chat_id))).all())
            excluded = {cid for cid, wa_id in chats if test_chat(wa_id)}
            rows = (
                await db.execute(
                    select(Message, ReviewFeedback, LearningExample)
                    .join(ReviewFeedback, ReviewFeedback.message_id == Message.id)
                    .join(LearningExample, LearningExample.message_id == Message.id)
                    .where(Message.chat_id.in_(excluded), LearningExample.enabled.is_(True))
                    .order_by(Message.sent_at, Message.id)
                    .limit(limit)
                )
            ).all()
            ctx = StageContext(
                db=db,
                moderator=client,
                model=cfg.ollama_model,
                thresholds=effective_thresholds(await get_setting(db, "classification.thresholds")),
                context_window_size=int(
                    await get_setting(db, "classification.context_window_size")
                ),
                context_max_age=timedelta(
                    hours=int(await get_setting(db, "classification.context_max_age_hours"))
                ),
            )
            issues = set(await db.scalars(select(ReviewDataIssue.message_id)))
            skipped_groups = set(
                (await db.execute(select(SkippedGroup.chat_id, SkippedGroup.instance_id))).all()
            )
            receipts: dict[int, set[int]] = {}
            for mid, iid in await db.execute(
                select(MessageReceipt.message_id, MessageReceipt.instance_id).where(
                    MessageReceipt.message_id.in_(select(LearningExample.message_id))
                )
            ):
                receipts.setdefault(mid, set()).add(iid)
            cases = []
            for message, feedback, example in rows:
                if (
                    not eligible(message)
                    or message.id in issues
                    or feedback.verdict not in {"safe", "harmful"}
                    or content_hash(message) != example.content_hash
                    or feedback.verdict != example.verdict
                    or (
                        feedback.content_hash is not None
                        and feedback.content_hash != example.content_hash
                    )
                    or (message.edited_at is not None and message.edited_at > feedback.reviewed_at)
                    or any(
                        (message.chat_id, iid) in skipped_groups
                        for iid in receipts.get(message.id, set())
                    )
                ):
                    continue
                cases.append((message, feedback, example))
            # Snapshot all potential training sources and context, not just the current
            # target. A revoked example/changed label must invalidate earlier pairs too.
            evidence = []
            for example, message, feedback in await db.execute(
                select(LearningExample, Message, ReviewFeedback)
                .join(Message, Message.id == LearningExample.message_id)
                .join(ReviewFeedback, ReviewFeedback.message_id == Message.id)
                .order_by(Message.id)
            ):
                evidence.append(
                    [
                        source_signature(message),
                        example.enabled,
                        example.content_hash,
                        example.verdict,
                        example.created_at,
                        feedback.verdict,
                        feedback.reviewed_at,
                        feedback.content_hash,
                        feedback.categories,
                        feedback.explanation,
                    ]
                )
            contexts = [
                [source_signature(m) for m in await context_messages(message, ctx)]
                for message, _, _ in cases
            ]
            configuration = await configuration_fingerprint(db)
            signature = fingerprint(
                [
                    configuration,
                    strategy,
                    evidence,
                    contexts,
                    [m.id for m, _, _ in cases],
                    sorted(issues),
                    sorted(skipped_groups),
                    {mid: sorted(ids) for mid, ids in receipts.items()},
                ]
            )
            state: dict[str, Any] = checkpoint if checkpoint is not None else {}
            if state.get("fingerprint") != signature:
                state.clear()
                state.update(fingerprint=signature, rows=[], attempts={}, errors={})
            evaluated = state["rows"]
            attempts, errors = state["attempts"], state["errors"]
            completed = {r["case_id"] for r in evaluated}
            keyed = [(fingerprint([m.id, e.content_hash]), m, f) for m, f, e in cases]
            todo = [
                (key, m, f)
                for key, m, f in keyed
                if key not in completed and attempts.get(key, 0) < 3
            ]
            if checkpoint is not None:
                todo = sorted(todo, key=lambda row: attempts.get(row[0], 0))[:1]
            started = time.monotonic()
            worker_budget = min(
                cfg.job_timeout_seconds, 570 if not cfg.job_heartbeat_seconds else 3600
            )
            budget = max(0, min(600, worker_budget - 75))
            for key, message, feedback in todo:
                if checkpoint is None and time.monotonic() - started >= budget:
                    break
                stage = "retrieval"
                attempts[key] = attempts.get(key, 0) + 1
                try:
                    selection = await asyncio.wait_for(
                        select_examples(
                            db,
                            message,
                            exclude_chats=excluded,
                            embedder=client,
                            strategy=strategy,
                        ),
                        request_timeout,
                    )
                    examples = selection.examples
                    if await get_setting(db, "classification.community_learning"):
                        from app.classify.community import guidance

                        examples = [*examples, *guidance(message_body(message))]
                    stage = "baseline"
                    baseline = await asyncio.wait_for(run_pipeline(message, ctx), request_timeout)
                    candidate = baseline
                    if examples:
                        stage = "candidate"
                        candidate = await asyncio.wait_for(
                            run_pipeline(message, replace(ctx, learning_examples=examples)),
                            request_timeout,
                        )
                except (PermanentError, TransientError, TimeoutError) as exc:
                    error = stage + ":" + type(exc).__name__
                    errors[error] = errors.get(error, 0) + 1
                    continue
                evaluated.append(
                    {
                        "case_id": key,
                        "conversation": fingerprint(message.chat_id),
                        "human": feedback.verdict,
                        "baseline": baseline.verdict,
                        "candidate": candidate.verdict,
                        "language": "he"
                        if re.search(r"[\u0590-\u05ff]", message_body(message))
                        else "en",
                        "matched": bool(examples),
                        "fallback": selection.metadata["fallback"] is not None,
                    }
                )
            completed = {r["case_id"] for r in evaluated}
            pending = sum(key not in completed and attempts.get(key, 0) < 3 for key, _, _ in keyed)
            failures = len(cases) - len(evaluated) - pending
            from app.classify.quality import metrics, paired_comparison, promotion_gate

            report = {
                "source": "held_out_human_reviews",
                "quality_policy": QUALITY_POLICY,
                "prompt_sha256": prompt_fingerprint(),
                "configuration_sha256": configuration,
                "model": cfg.ollama_model,
                "checked_at": datetime.now(UTC).isoformat(),
                "evaluated": len(evaluated),
                "expected": len(cases),
                "skipped": len(rows) - len(cases),
                "pending": pending,
                "failures": failures,
                "request_errors": errors,
                "baseline": metrics(evaluated, "baseline"),
                "candidate": metrics(evaluated, "candidate"),
                "paired": paired_comparison(evaluated, unit="conversation"),
                "retrieval_matches": sum(r["matched"] for r in evaluated),
                "embedding_fallbacks": sum(r["fallback"] for r in evaluated),
                "split": "Whole conversations held out; no messages or identifiers exported",
                "languages": {
                    lang: {
                        field: metrics([r for r in evaluated if r["language"] == lang], field)
                        for field in ("baseline", "candidate")
                    }
                    for lang in ("he", "en")
                },
                "weights_updated": False,
                "user_data_exported": False,
            }
            report["promotion"] = promotion_gate(report)
            if emit:
                print(json.dumps(report, indent=2))
            return report
    finally:
        if client is not None:
            await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, choices=range(1, 201), metavar="1..200")
    parser.add_argument("--retrieval", choices=("lexical", "semantic"), default=None)
    args = parser.parse_args()
    asyncio.run(evaluate(args.limit, args.retrieval))
