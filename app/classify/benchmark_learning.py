"""Read-only evaluation. Run: python -m app.classify.benchmark_learning --limit 30."""

import argparse
import asyncio
import hashlib
import json
import re
import time
from dataclasses import replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.classify.learning import content_hash, eligible, select_examples
from app.classify.ollama import OllamaModerator
from app.classify.pipeline import run_pipeline
from app.classify.stages import StageContext
from app.classify.thresholds import effective_thresholds
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.models import Chat, LearningExample, Message, ReviewFeedback
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


async def evaluate(limit: int, strategy: str | None = None, *, emit: bool = True) -> dict[str, Any]:
    engine = make_engine()
    factory = make_session_factory(engine)
    client = None
    try:
        async with factory() as db:
            await reload_runtime_settings(db)
            cfg = get_settings()
            client = OllamaModerator(cfg.ollama_base_url, cfg.ollama_model)
            chats = list((await db.execute(select(Chat.id, Chat.wa_chat_id))).all())
            excluded = {cid for cid, wa_id in chats if test_chat(wa_id)}
            rows = await db.execute(
                select(Message, ReviewFeedback, LearningExample)
                .join(ReviewFeedback, ReviewFeedback.message_id == Message.id)
                .join(LearningExample, LearningExample.message_id == Message.id)
                .where(Message.chat_id.in_(excluded), LearningExample.enabled.is_(True))
                .order_by(Message.sent_at, Message.id)
                .limit(limit)
            )
            ctx = StageContext(
                db=db,
                moderator=client,
                model=cfg.ollama_model,
                thresholds=effective_thresholds(await get_setting(db, "classification.thresholds")),
                context_window_size=int(
                    await get_setting(db, "classification.context_window_size")
                ),
                context_max_age=timedelta(
                    hours=int(await get_setting(db, "classification.context_max_age_hours")),
                ),
            )
            evaluated: list[dict[str, Any]] = []
            skipped = failures = 0
            fallbacks = 0
            matched = 0
            started = time.monotonic()
            for message, feedback, example in rows:
                if time.monotonic() - started > 600:
                    failures += 1
                    break
                if (
                    not eligible(message)
                    or content_hash(message) != example.content_hash
                    or feedback.verdict != example.verdict
                    or (message.edited_at is not None and message.edited_at > feedback.reviewed_at)
                ):
                    skipped += 1
                    continue
                selection = await select_examples(
                    db,
                    message,
                    exclude_chats=excluded,
                    embedder=client,
                    strategy=strategy,
                )
                examples = selection.examples
                if await get_setting(db, "classification.community_learning"):
                    from app.classify.community import guidance
                    from app.classify.stages import message_body

                    examples = [*examples, *guidance(message_body(message))]
                fallbacks += selection.metadata["fallback"] is not None
                try:
                    baseline = await asyncio.wait_for(run_pipeline(message, ctx), 30)
                    candidate = baseline
                    if examples:
                        matched += 1
                        candidate = await asyncio.wait_for(
                            run_pipeline(message, replace(ctx, learning_examples=examples)), 30
                        )
                except (PermanentError, TransientError, TimeoutError):
                    failures += 1
                    continue
                evaluated.append(
                    {
                        "human": feedback.verdict,
                        "baseline": baseline.verdict,
                        "candidate": candidate.verdict,
                        "language": "he"
                        if re.search(r"[\u0590-\u05ff]", message.text or "")
                        else "en",
                    }
                )
            if emit:
                print(
                    json.dumps(
                        {
                            "split": "sha256(chat ID) modulo 5: 0=test; all test chats excluded",
                            "model": cfg.ollama_model,
                            "evaluated": len(evaluated),
                            "skipped": skipped,
                            "failures": failures,
                            "retrieval": strategy
                            or await get_setting(db, "classification.learning_retrieval"),
                            "embedding_model": await get_setting(
                                db, "classification.learning_embedding_model"
                            ),
                            "embedding_fallbacks": fallbacks,
                            "retrieval_matches": matched,
                            "baseline": summarize(evaluated, "baseline"),
                            "candidate": summarize(evaluated, "candidate"),
                            "limitations": (
                                "Reviewed text only; not population accuracy. "
                                "Targets without retrieval matches use baseline for candidate. "
                                "Human labels are overall verdicts, not category labels. "
                                "No message content exported."
                            ),
                        },
                        indent=2,
                    )
                )
            from app.classify.evaluation import metrics, promotion_gate

            report = {
                "source": "held_out_human_reviews",
                "model": cfg.ollama_model,
                "evaluated": len(evaluated),
                "failures": failures,
                "baseline": metrics(evaluated, "baseline"),
                "candidate": metrics(evaluated, "candidate"),
                "retrieval_matches": matched,
                "embedding_fallbacks": fallbacks,
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
