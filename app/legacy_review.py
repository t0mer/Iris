"""Startup quarantine of old skipped messages whose original type was lost."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Classification, Job, Message, ReviewFeedback
from app.review_queue import EXHAUSTED_REVIEW, OPENWA_RECOVERY_ERROR


async def quarantine_legacy_unknowns(db: AsyncSession) -> None:
    await db.execute(
        update(Message)
        .where(
            Message.type == "other",
            Message.status == "skipped",
            Message.verdict.is_(None),
            Message.raw_type.is_(None),
        )
        .values(
            status="done",
            verdict="review",
            skip_reason=None,
            review_reason="Unknown legacy message; original type and skip reason unavailable",
        )
    )
    # Captions/filenames were previously mistaken for an examined document.
    # Preserve explicit parent decisions and harmful findings.
    await db.execute(
        update(Message)
        .where(
            Message.type == "document",
            Message.verdict == "safe",
            Message.id.not_in(select(ReviewFeedback.message_id)),
            ~select(Classification.id)
            .where(
                Classification.message_id == Message.id,
                Classification.scores["_meta"]["media_analysis"]["method"]
                .as_string()
                .in_(
                    [
                        "pdf_text_v1",
                        "docx_text_v1",
                        "plain_text_v1",
                        "attachment_image_v1",
                        "attachment_audio_v1",
                        "sampled_video_v1",
                        "sampled_video_v2",
                    ]
                ),
                Classification.scores["_meta"]["media_analysis"]["complete"].as_boolean() == True,  # noqa: E712
            )
            .exists(),
        )
        .values(verdict="review", review_reason="Document attachment requires manual review")
    )
    await db.execute(
        update(Message)
        .where(
            Message.status == "failed",
            Message.verdict.is_(None),
        )
        .values(verdict="review", review_reason="Safety check unavailable; parent review required")
    )
    # Only repair the generic terminal reason when the latest processing job
    # confirms this exact recovery failure. Never infer a verdict from a failed fetch.
    latest_error = (
        select(Job.last_error)
        .where(Job.type == "process_message", Job.payload["message_id"].as_integer() == Message.id)
        .order_by(Job.id.desc())
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    )
    await db.execute(
        update(Message)
        .where(
            Message.status == "failed",
            Message.verdict == "review",
            Message.review_reason == EXHAUSTED_REVIEW,
            Message.id.not_in(select(ReviewFeedback.message_id)),
            latest_error == OPENWA_RECOVERY_ERROR,
        )
        .values(review_reason=OPENWA_RECOVERY_ERROR)
    )
    await db.commit()
