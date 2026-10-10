"""Shared queue membership: AI work must not appear as an actionable human review."""

from sqlalchemy import ColumnElement, or_, select

from app.db.models import Job, Message


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
