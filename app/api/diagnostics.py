"""Aggregate operational diagnostics without message content or provider credentials."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LearningExample, Message, ReviewFeedback
from app.deps import get_db
from app.review_queue import ai_pending, unavailable_content
from app.security.auth import admin_user

router = APIRouter(
    prefix="/api/diagnostics", tags=["diagnostics"], dependencies=[Depends(admin_user)]
)


def review_category(reason: str | None) -> str:
    """Stable categories; never echo provider errors or free text to integrations."""
    reason = (reason or "").lower()
    if "media" in reason and any(word in reason for word in ("no stored", "no media")):
        return "missing_media"
    if "whisper" in reason or "transcript" in reason:
        return "transcription_failed"
    if "after retries" in reason:
        return "processing_failed"
    if "inconclusive" in reason:
        return "inconclusive"
    if "legacy" in reason:
        return "legacy_incomplete"
    if "unknown" in reason:
        return "unsupported_type"
    if "decode" in reason:
        return "media_decode_failed"
    if "document" in reason or "pdf" in reason:
        return "document_review"
    if "video" in reason:
        return "video_review"
    if "image" in reason:
        return "image_review"
    return "other_review"


@router.get("/summary")
async def summary(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    """Separate processing backlog, unresolved review, failures and learning label counts."""
    pending = int(
        await db.scalar(select(func.count()).select_from(Message).where(ai_pending())) or 0
    )
    grouped = await db.execute(
        select(Message.type, Message.review_reason, func.count())
        .where(
            Message.verdict == "review",
            ~ai_pending(),
            ~select(ReviewFeedback.message_id)
            .where(ReviewFeedback.message_id == Message.id)
            .exists(),
        )
        .group_by(Message.type, Message.review_reason)
    )
    categories: dict[str, int] = {}
    media_types: dict[str, int] = {}
    for media_type, reason, count in grouped:
        key = review_category(reason)
        categories[key] = categories.get(key, 0) + count
        media_types[media_type] = media_types.get(media_type, 0) + count
    jobs = [
        {"type": kind, "status": status, "count": count}
        for kind, status, count in await db.execute(
            select(Job.type, Job.status, func.count()).group_by(Job.type, Job.status)
        )
    ]
    labels = dict(
        (
            await db.execute(
                select(ReviewFeedback.verdict, func.count()).group_by(ReviewFeedback.verdict)
            )
        ).all()
    )
    examples = dict(
        (
            await db.execute(
                select(LearningExample.verdict, func.count())
                .where(LearningExample.enabled.is_(True))
                .group_by(LearningExample.verdict)
            )
        ).all()
    )
    unavailable = int(
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.verdict == "review",
                ~ai_pending(),
                unavailable_content(),
                ~select(ReviewFeedback.message_id)
                .where(ReviewFeedback.message_id == Message.id)
                .exists(),
            )
        )
        or 0
    )
    return {
        "pending_processing": pending,
        "manual_review": sum(categories.values()) - unavailable,
        "unavailable_content": unavailable,
        "unresolved_review": {
            "total": sum(categories.values()),
            "by_reason": categories,
            "by_type": media_types,
        },
        "jobs": jobs,
        "learning": {
            "human_labels": labels,
            "enabled_examples": examples,
            "note": "Counts are not held-out eligibility or evidence of model accuracy.",
        },
    }
