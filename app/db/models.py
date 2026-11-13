"""SQLAlchemy models (spec §6). Timestamps are UTC."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import UTCDateTime


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(**kw: Any) -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), default=_now, **kw)


class Base(DeclarativeBase):
    pass


class Instance(Base):
    __tablename__ = "instances"
    id: Mapped[int] = mapped_column(primary_key=True)
    kid_name: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(255))
    openwa_base_url: Mapped[str] = mapped_column(String(255))
    openwa_instance_id: Mapped[str] = mapped_column(String(255))
    openwa_api_key_enc: Mapped[str | None] = mapped_column(Text)
    webhook_token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # True once Iris registered the webhook with an HMAC secret: signatures are then mandatory.
    signature_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _ts()
    last_webhook_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_chat_id: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = _ts()


class ChatInstance(Base):
    __tablename__ = "chat_instances"
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
    )


class SkippedGroup(Base):
    __tablename__ = "skipped_groups"
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("chat_id", "wa_message_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_message_id: Mapped[str] = mapped_column(String(255))
    chat_id: Mapped[int] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    sender_wa_id: Mapped[str | None] = mapped_column(String(255))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    from_me: Mapped[bool] = mapped_column(Boolean, default=False)
    type: Mapped[str] = mapped_column(String(255))
    text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    quoted_wa_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    received_at: Mapped[datetime] = _ts()
    status: Mapped[str] = mapped_column(String(255), default="pending", index=True)
    verdict: Mapped[str | None] = mapped_column(String(255), index=True)
    review_reason: Mapped[str | None] = mapped_column(String(255))
    skip_reason: Mapped[str | None] = mapped_column(String(255))
    raw_type: Mapped[str | None] = mapped_column(String(255))
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    # How to fetch the media from OpenWA: {instance_id, chat_id, message_ref, mimetype, ...}.
    # Kept on the message (not only the job) so reprocessing media messages keeps working.
    media: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    # Set when OpenWA reports an edit / a delete-for-everyone (received time, not WhatsApp's).
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class StoredMedia(Base):
    """A kept copy of a message's media. No foreign key on purpose: the row (and so the object
    it points at) must outlive a deleted message until the sweeper has removed the object."""

    __tablename__ = "stored_media"
    __table_args__ = (UniqueConstraint("message_id", "sha256"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(index=True)
    backend: Mapped[str] = mapped_column(String(255))  # local | s3
    # Where an S3 object really lives (endpoint, bucket, folder, region, addressing as JSON), so a
    # later change of the settings cannot strand it. Empty for local files.
    location: Mapped[str] = mapped_column(String(1024), default="", server_default="")
    key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(255))  # image | audio | video
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts()
    purge: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), index=True)
    purge_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MessageRevision(Base):
    """The text an edit replaced. The oldest row is the original wording."""

    __tablename__ = "message_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    replaced_at: Mapped[datetime] = _ts()


class MessageReceipt(Base):
    __tablename__ = "message_receipts"
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True
    )
    received_at: Mapped[datetime] = _ts()


class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(255))
    input_kind: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    flagged_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    band: Mapped[str] = mapped_column(String(255))
    context_message_ids: Mapped[list[int] | None] = mapped_column(JSON(none_as_null=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True
    )
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    kid_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    chat_name: Mapped[str | None] = mapped_column(String(255))
    sender_name: Mapped[str | None] = mapped_column(String(255))
    quote: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(255), default="new", index=True)
    delivery_status: Mapped[str] = mapped_column(String(255), default="pending")
    delivery_error: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)


class AlertView(Base):
    """Personal read/dismiss state; never changes the shared safety decision."""

    __tablename__ = "alert_views"
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="new")
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MediaWarningDismissal(Base):
    """Hide a missing-media warning for this user without reading the alert."""

    __tablename__ = "media_warning_dismissals"
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(255), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_after: Mapped[datetime] = _ts()
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="admin", server_default="admin")
    email: Mapped[str | None] = mapped_column(String(255))
    whatsapp_number: Mapped[str | None] = mapped_column(String(16))
    email_contact_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    whatsapp_contact_key: Mapped[str | None] = mapped_column(String(16), unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    whatsapp_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    language: Mapped[str] = mapped_column(String(32), default="system", server_default="system")
    created_at: Mapped[datetime] = _ts()


class LoginChallenge(Base):
    __tablename__ = "login_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewFeedback(Base):
    __tablename__ = "review_feedback"
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    verdict: Mapped[str] = mapped_column(String(20))
    reviewed_at: Mapped[datetime] = _ts()
    categories: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))
    explanation: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class ReviewDataIssue(Base):
    """Data-quality reports are independent of human safety judgements."""

    __tablename__ = "review_data_issues"
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    issue: Mapped[str] = mapped_column(String(32))
    reported_at: Mapped[datetime] = _ts()


class LearningExample(Base):
    """A reviewed label bound to exact source content, without a second content copy."""

    __tablename__ = "learning_examples"
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _ts()


class LearningRun(Base):
    """Comparison evidence; contains scores and source IDs, never message content."""

    __tablename__ = "learning_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieval_version: Mapped[str] = mapped_column(String(40))
    retrieval: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    baseline_verdict: Mapped[str] = mapped_column(String(20))
    candidate_verdict: Mapped[str | None] = mapped_column(String(20))
    example_ids: Mapped[list[int]] = mapped_column(JSON)
    baseline_scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _ts()


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_key: Mapped[str] = mapped_column(String(80), index=True)
    job_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = _ts()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(255))
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(512))
    status_code: Mapped[int] = mapped_column(Integer)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _ts(index=True)


class SendingBudget(Base):
    """Persistent outbound pacing; reservations survive restarts."""

    __tablename__ = "sending_budgets"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    next_allowed: Mapped[datetime] = mapped_column(UTCDateTime())
    hour_start: Mapped[datetime] = mapped_column(UTCDateTime())
    hour_count: Mapped[int] = mapped_column(Integer, default=0)
    day_start: Mapped[datetime] = mapped_column(UTCDateTime())
    day_count: Mapped[int] = mapped_column(Integer, default=0)


class AlertAction(Base):
    """Recipient-bound, expiring review buttons; provider credentials are never stored."""

    __tablename__ = "alert_actions"
    token: Mapped[str] = mapped_column(String(48), primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    target: Mapped[str] = mapped_column(String(255))
    destination: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(20))
    provider_key: Mapped[str] = mapped_column(String(64))
    choice: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ReviewResponse(Base):
    __tablename__ = "review_responses"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(255))
    choice: Mapped[str] = mapped_column(String(20))
    applied: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
