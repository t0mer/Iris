"""Inspect/revoke examples and inspect comparison evidence. Admin-only, no raw text exports."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.community import public_manifest
from app.classify.evaluation import RESULT_KEY
from app.classify.learning import capture, content_hash, eligible
from app.db.models import Job, LearningExample, LearningRun, Message, ReviewFeedback, Setting
from app.deps import get_db
from app.jobs.queue import enqueue
from app.security.auth import admin_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api/learning", tags=["learning"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/evaluation")
async def evaluation_status(db: DB) -> dict[str, Any]:
    result = await db.get(Setting, RESULT_KEY)
    running = await db.scalar(
        select(Job.id)
        .where(Job.type == "evaluate_learning", Job.status.in_(("queued", "running")))
        .limit(1)
    )
    return {
        "result": result.value if result else None,
        "running": bool(running),
        "community_pack": public_manifest(),
        "community_enabled": await get_setting(db, "classification.community_learning"),
    }


@router.post("/evaluation")
async def start_evaluation(
    db: DB, source: Literal["synthetic", "held_out_human_reviews"] = "synthetic"
) -> dict[str, Any]:
    running = await db.scalar(
        select(Job.id)
        .where(Job.type == "evaluate_learning", Job.status.in_(("queued", "running")))
        .limit(1)
    )
    if running:
        return {"job_id": running}
    job = await enqueue(db, "evaluate_learning", {"source": source}, max_attempts=1)
    await db.commit()
    return {"job_id": job}


class ExampleUpdate(BaseModel):
    enabled: bool


@router.post("/examples/import")
async def import_reviews(db: DB, after: int = Query(0, ge=0)) -> dict[str, int]:
    rows = await db.execute(
        select(Message, ReviewFeedback)
        .join(ReviewFeedback, ReviewFeedback.message_id == Message.id)
        .where(
            ReviewFeedback.verdict.in_(("safe", "harmful")),
            Message.id > after,
            ~select(LearningExample.message_id)
            .where(LearningExample.message_id == Message.id)
            .exists(),
        )
        .order_by(Message.id)
        .limit(1000)
    )
    imported = 0
    next_cursor = after
    scanned = 0
    for message, feedback in rows:
        next_cursor = message.id
        scanned += 1
        if not eligible(message):
            continue
        if message.edited_at is not None and message.edited_at > feedback.reviewed_at:
            continue
        await capture(db, message, feedback.verdict)
        await db.flush()
        imported += await db.get(LearningExample, message.id) is not None
    await db.commit()
    return {"imported": imported, "next_cursor": next_cursor, "scanned": scanned}


@router.get("/examples")
async def examples(db: DB, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    rows = await db.execute(
        select(LearningExample, Message)
        .join(Message, Message.id == LearningExample.message_id)
        .order_by(LearningExample.created_at.desc())
        .limit(limit)
    )
    return {
        "items": [
            {
                "message_id": e.message_id,
                "verdict": e.verdict,
                "enabled": e.enabled,
                "source_valid": eligible(m) and content_hash(m) == e.content_hash,
                "created_at": e.created_at,
            }
            for e, m in rows
        ],
        "retrieval_strategy": await get_setting(db, "classification.learning_retrieval"),
    }


@router.patch("/examples/{message_id}")
async def update_example(message_id: int, body: ExampleUpdate, db: DB) -> dict[str, bool]:
    row = await db.get(LearningExample, message_id)
    if row is None:
        raise HTTPException(404, "Learning example not found")
    row.enabled = body.enabled
    await db.commit()
    return {"ok": True}


@router.delete("/runs")
async def clear_runs(db: DB) -> dict[str, bool]:
    await db.execute(delete(LearningRun))
    await db.commit()
    return {"ok": True}


@router.get("/runs")
async def runs(db: DB, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = list(await db.scalars(select(LearningRun).order_by(LearningRun.id.desc()).limit(limit)))
    feedback = {
        f.message_id: (f, m)
        for f, m in await db.execute(
            select(ReviewFeedback, Message)
            .join(Message, Message.id == ReviewFeedback.message_id)
            .where(
                ReviewFeedback.message_id.in_([r.message_id for r in rows]),
                ReviewFeedback.verdict.in_(("safe", "harmful")),
            )
        )
    }
    labels = {mid: f.verdict for mid, (f, _) in feedback.items()}
    # One latest comparison per message prevents reprocessing from inflating the summary.
    latest: dict[int, LearningRun] = {}
    for row in rows:
        latest.setdefault(row.message_id, row)
    evaluated = []
    for r in latest.values():
        if r.message_id not in feedback or r.error is not None:
            continue
        f, m = feedback[r.message_id]
        if eligible(m) and content_hash(m) == r.content_hash and f.reviewed_at >= r.created_at:
            evaluated.append(r)

    def metrics(field: str) -> dict[str, Any]:
        tp = fp = fn = tn = abstained = 0
        for row in evaluated:
            predicted = getattr(row, field)
            actual = labels[row.message_id]
            tp += predicted == "harmful" and actual == "harmful"
            fp += predicted == "harmful" and actual == "safe"
            fn += predicted == "safe" and actual == "harmful"
            tn += predicted == "safe" and actual == "safe"
            abstained += predicted == "review"
        return {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "review": abstained,
            "precision": tp / (tp + fp) if tp + fp else None,
            "harmful_detection_rate": tp / sum(labels[r.message_id] == "harmful" for r in evaluated)
            if any(labels[r.message_id] == "harmful" for r in evaluated)
            else None,
        }

    return {
        "mode": await get_setting(db, "classification.learning_mode"),
        "retrieval_strategy": await get_setting(db, "classification.learning_retrieval"),
        "retrieval_versions": sorted({r.retrieval_version for r in rows}),
        "summary": {
            "sampled_runs": len(rows),
            "reviewed_messages": len(evaluated),
            "baseline": metrics("baseline_verdict"),
            "candidate": metrics("candidate_verdict"),
        },
        "items": [
            {
                "id": r.id,
                "message_id": r.message_id,
                "mode": r.mode,
                "model": r.model,
                "retrieval_version": r.retrieval_version,
                "retrieval": r.retrieval,
                "baseline_verdict": r.baseline_verdict,
                "candidate_verdict": r.candidate_verdict,
                "human_verdict": labels.get(r.message_id),
                "example_ids": r.example_ids,
                "baseline_scores": r.baseline_scores,
                "candidate_scores": r.candidate_scores,
                "thresholds": r.thresholds,
                "latency_ms": r.latency_ms,
                "error": r.error,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }
