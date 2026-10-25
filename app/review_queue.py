"""Shared queue membership: AI work must not appear as an actionable human review."""

from sqlalchemy import ColumnElement, case, func, or_, select

from app.db.models import Job, Message, ReviewDataIssue


def review_kind() -> ColumnElement[str]:
    """Operational reason, not a safety verdict or an urgency prediction."""
    reason = func.lower(func.coalesce(Message.review_reason, ""))
    return case(
        (unavailable_content(), "unavailable"),
        (reason.contains("inconclusive"), "uncertain"),
        (
            or_(
                *(
                    reason.contains(word)
                    for word in (
                        "failed",
                        "unavailable",
                        "timeout",
                        "timed out",
                        "ffmpeg",
                        "whisper",
                        "after retries",
                    )
                )
            ),
            "technical",
        ),
        (
            or_(
                Message.type.in_(("image", "sticker", "video", "voice", "audio", "document")),
                (Message.type == "other") & Message.media["message_ref"].as_string().is_not(None),
            ),
            "attachment",
        ),
        else_="uncertain",
    )


def unavailable_content() -> ColumnElement[bool]:
    """Route confirmed data failures separately; never create a human safety label.

    Hidden content and exact machine reasons only. Inconclusive scores, unsupported documents/video,
    decoder failures and arbitrary provider errors still require review or recovery.
    Coalesce is necessary so a missing reason remains in the normal review queue.
    """
    reported = (
        select(ReviewDataIssue.message_id).where(ReviewDataIssue.message_id == Message.id).exists()
    )
    return or_(
        reported,
        Message.redacted.is_(True),
        Message.revoked_at.is_not(None),
        func.coalesce(Message.review_reason, "").in_(
            (
                "OpenWA has no stored media for this message (check its inbound media storage)",
                "message has no media reference",
                "Unknown message type; no analyzable content",
            )
        ),
    )


def ai_pending() -> ColumnElement[bool]:
    active = (
        select(Job.id)
        .where(
            Job.type == "process_message",
            Job.status.in_(("queued", "running")),
            Job.payload["message_id"].as_integer() == Message.id,
        )
        .exists()
    )
    return or_(Message.status.in_(("pending", "processing")), active)
