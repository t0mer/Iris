"""/api/alerts and /api/review: alert list/detail/actions and the review queue."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import ColumnElement, and_, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.media_status import missing_media_copy
from app.alerts.service import (
    DELIVERY_ATTEMPTS,
    DELIVERY_JOB,
    delivery_configured,
)
from app.api.media import MediaOut, media_out
from app.api.messages import (
    ClassificationOut,
    MessageOut,
    _failures,
    _kids,
    _load,
    _to_out,
)
from app.config import Settings, get_settings
from app.db.jsonq import json_array_contains
from app.db.models import (
    Alert,
    AlertView,
    Classification,
    Job,
    Message,
    MessageReceipt,
    ReviewDataIssue,
    ReviewFeedback,
    StoredMedia,
    User,
)
from app.deps import get_db
from app.jobs.queue import enqueue
from app.review_queue import ai_pending
from app.security.auth import current_user, parent_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["alerts"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


class AlertOut(BaseModel):
    seen_at: datetime | None = None
    verdict: str | None = None
    review_reason: str | None = None
    id: int
    message_id: int
    chat_id: int
    categories: list[str]
    max_score: float
    kid_names: list[str]
    chat_name: str | None
    sender_name: str | None
    quote: str | None
    redacted: bool  # content withheld (spec 8.5): the alert carries metadata only
    status: str
    delivery_status: str
    delivery_error: str | None
    notified_at: datetime | None
    created_at: datetime
    edited_at: datetime | None  # the message was edited after the alert
    revoked_at: datetime | None  # the sender deleted it for everyone
    media: MediaOut | None = None  # a kept copy of the message's media, when there is one


class AlertDetail(AlertOut):
    message_type: str
    sent_at: datetime
    classifications: list[ClassificationOut]
    recipient_delivery: list[dict[str, str]] = []
    response_notes: list[dict[str, Any]] = []
    sending_server: str = ""


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int
    page: int
    page_size: int


def _out(
    a: Alert, m: Message, media: StoredMedia | None = None, view: AlertView | None = None
) -> AlertOut:
    return AlertOut(
        id=a.id,
        verdict=m.verdict,
        review_reason=m.review_reason,
        message_id=a.message_id,
        chat_id=m.chat_id,
        categories=list(a.categories),
        max_score=a.max_score,
        kid_names=list(a.kid_names),
        chat_name=a.chat_name,
        sender_name=a.sender_name,
        quote=None if m.redacted else a.quote,
        redacted=m.redacted,
        status=view.status if view else "new",
        seen_at=view.seen_at if view else None,
        delivery_status=a.delivery_status,
        delivery_error=a.delivery_error,
        edited_at=m.edited_at,
        revoked_at=m.revoked_at,
        notified_at=a.notified_at,
        created_at=a.created_at,
        media=media_out(media) if media is not None and not m.redacted else None,
    )


async def _media_by_message(db: AsyncSession, message_ids: list[int]) -> dict[int, StoredMedia]:
    """The shown copy for each message (one query for a whole page of alerts)."""
    if not message_ids:
        return {}
    rows = await db.execute(
        select(StoredMedia)
        .where(StoredMedia.message_id.in_(message_ids), StoredMedia.purge.is_(False))
        .order_by(StoredMedia.id.desc())
    )
    return {r.message_id: r for r in rows.scalars()}


@router.get("/alerts")
async def list_alerts(
    db: DB,
    user: Annotated[User, Depends(current_user)],
    view: Literal["unseen", "seen", "all", "dismissed"] = "unseen",
    status: str | None = None,
    delivery_status: str | None = None,
    media: Literal["missing"] | None = None,
    instance_id: int | None = None,
    chat_id: int | None = None,
    category: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> AlertPage:
    conds: list[ColumnElement[bool]] = []
    if status:
        if status not in {"new", "acknowledged", "dismissed"}:
            raise HTTPException(422, "Invalid alert status")
        if status == "new":
            view = "unseen"
        elif status == "acknowledged":
            view = "seen"
        else:
            view = "dismissed"
    personal_status = func.coalesce(AlertView.status, "new")
    if view == "unseen":
        conds.append(personal_status == "new")
    elif view == "seen":
        conds.append(personal_status != "new")
    elif view == "dismissed":
        conds.append(personal_status == "dismissed")
    if media == "missing":
        conds.append(missing_media_copy())
    if delivery_status:
        conds.append(Alert.delivery_status == delivery_status)
    if instance_id is not None:
        conds.append(
            exists().where(
                MessageReceipt.message_id == Alert.message_id,
                MessageReceipt.instance_id == instance_id,
            )
        )
    if chat_id is not None:
        conds.append(Message.chat_id == chat_id)
    if category:
        conds.append(json_array_contains(Alert.categories, category))
    if from_:
        conds.append(Alert.created_at >= from_)
    if to:
        conds.append(Alert.created_at <= to)
    where = and_(*conds) if conds else None
    owned_view = and_(AlertView.alert_id == Alert.id, AlertView.user_id == user.id)
    base = (
        select(Alert, Message, AlertView)
        .join(Message, Message.id == Alert.message_id)
        .outerjoin(AlertView, owned_view)
    )
    count = (
        select(func.count())
        .select_from(Alert)
        .join(Message, Message.id == Alert.message_id)
        .outerjoin(AlertView, owned_view)
    )
    if where is not None:
        base, count = base.where(where), count.where(where)
    total = int((await db.execute(count)).scalar_one())
    rows = (
        await db.execute(
            base.order_by(Alert.created_at.desc(), Alert.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    kept_media = await _media_by_message(db, [m.id for _, m, _ in rows])
    return AlertPage(
        items=[_out(a, m, kept_media.get(m.id), v) for a, m, v in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _alert(db: AsyncSession, alert_id: int) -> tuple[Alert, Message]:
    row = (
        await db.execute(
            select(Alert, Message)
            .join(Message, Message.id == Alert.message_id)
            .where(Alert.id == alert_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return row[0], row[1]


class SeenBatch(BaseModel):
    alert_ids: list[int] = Field(min_length=1, max_length=100)


@router.post("/alerts/seen")
async def mark_page_seen(
    body: SeenBatch, db: DB, user: Annotated[User, Depends(current_user)]
) -> dict[str, Any]:
    ids = sorted(set(body.alert_ids))
    # Serialize with individual read/dismiss writes, preserving shared alert fields.
    await db.execute(
        update(Alert)
        .where(Alert.id.in_(ids))
        .values(status=Alert.status, updated_at=Alert.updated_at)
    )
    existing = set(await db.scalars(select(Alert.id).where(Alert.id.in_(ids))))
    if existing != set(ids):
        raise HTTPException(404, "Alert not found")
    views = {
        v.alert_id: v
        for v in await db.scalars(
            select(AlertView).where(AlertView.alert_id.in_(ids), AlertView.user_id == user.id)
        )
    }
    now = datetime.now(UTC)
    marked = 0
    for alert_id in ids:
        personal = views.get(alert_id)
        if personal is None:
            db.add(
                AlertView(alert_id=alert_id, user_id=user.id, status="acknowledged", seen_at=now)
            )
            marked += 1
        elif personal.status == "new":
            personal.status, personal.seen_at = "acknowledged", now
            marked += 1
    await db.commit()
    return {"marked": marked, "seen_at": now}


@router.get("/alerts/{alert_id}")
async def get_alert(
    alert_id: int, db: DB, user: Annotated[User, Depends(current_user)]
) -> AlertDetail:
    a, m = await _alert(db, alert_id)
    cls = (
        await db.execute(
            select(Classification)
            .where(Classification.message_id == m.id)
            .order_by(Classification.id)
        )
    ).scalars()
    latest = await db.scalar(
        select(Job)
        .where(Job.type == DELIVERY_JOB, Job.payload["alert_id"].as_integer() == alert_id)
        .order_by(Job.id.desc())
        .limit(1)
    )
    deliveries = []
    if latest is not None:
        payload = latest.payload
        for target in payload.get("recipients", []):
            status = (
                "delivered"
                if target in payload.get("delivered_recipients", [])
                else "uncertain"
                if target in payload.get("uncertain_recipients", [])
                else "rejected"
                if target in payload.get("rejected_recipients", {})
                else "not sent"
                if latest.status == "failed"
                else "pending"
            )
            label = (
                "Email " + target.removeprefix("email:").split("@")[0][:1] + "…"
                if target.startswith("email:")
                else "Recipient ending " + target.split("@")[0][-4:]
            )
            deliveries.append({"recipient": label, "status": status})
    return AlertDetail(
        **_out(
            a,
            m,
            (await _media_by_message(db, [m.id])).get(m.id),
            await db.get(AlertView, (a.id, user.id)),
        ).model_dump(),
        recipient_delivery=deliveries,
        sending_server=str(
            await get_setting(db, "runtime.public_base_url") or get_settings().public_base_url
        ),
        response_notes=await response_notes(db, m.id),
        message_type=m.type,
        sent_at=m.sent_at,
        classifications=[ClassificationOut.model_validate(c, from_attributes=True) for c in cls],
    )


class AlertPatch(BaseModel):
    status: Literal["new", "acknowledged", "dismissed"]


@router.patch("/alerts/{alert_id}", dependencies=[Depends(parent_user)])
async def patch_alert(
    alert_id: int, body: AlertPatch, db: DB, user: Annotated[User, Depends(current_user)]
) -> AlertOut:
    a, m = await _alert(db, alert_id)
    personal = await _set_view(db, a.id, user.id, body.status)
    return _out(a, m, (await _media_by_message(db, [m.id])).get(m.id), personal)


async def _set_view(
    db: AsyncSession, alert_id: int, user_id: int, status: str, preserve_dismissed: bool = False
) -> AlertView:
    # A short write lock makes repeated opens from multiple tabs idempotent across processes.
    await db.execute(
        update(Alert)
        .where(Alert.id == alert_id)
        .values(status=Alert.status, updated_at=Alert.updated_at)
    )
    personal = await db.get(AlertView, (alert_id, user_id))
    if personal is None:
        personal = AlertView(alert_id=alert_id, user_id=user_id, status=status)
        db.add(personal)
    elif not (preserve_dismissed and personal.status == "dismissed"):
        personal.status = status
    personal.seen_at = None if personal.status == "new" else (personal.seen_at or datetime.now(UTC))
    await db.commit()
    # Return the persisted timestamp, including the database's datetime precision.
    await db.refresh(personal)
    return personal


class SeenPatch(BaseModel):
    seen: bool = True


@router.post("/alerts/{alert_id}/seen")
async def mark_seen(
    alert_id: int, body: SeenPatch, db: DB, user: Annotated[User, Depends(current_user)]
) -> AlertOut:
    a, m = await _alert(db, alert_id)
    personal = await _set_view(
        db, alert_id, user.id, "acknowledged" if body.seen else "new", preserve_dismissed=body.seen
    )
    return _out(a, m, (await _media_by_message(db, [m.id])).get(m.id), personal)


@router.post("/alerts/{alert_id}/resend", dependencies=[Depends(parent_user)])
async def resend_alert(alert_id: int, db: DB) -> dict[str, bool]:
    a, _ = await _alert(db, alert_id)
    if not await delivery_configured(db):
        from app.alerts.readiness import delivery_readiness

        raise HTTPException(
            422, "Alert delivery is not configured: " + (await delivery_readiness(db)).error
        )
    if await _delivery_active(db, a.id):
        raise HTTPException(status_code=409, detail="Delivery already in progress")
    payload = {"alert_id": a.id, "force": True}
    if a.delivery_status in ("partial", "failed"):
        previous = await db.scalar(
            select(Job)
            .where(Job.type == DELIVERY_JOB, Job.payload["alert_id"].as_integer() == a.id)
            .order_by(Job.id.desc())
            .limit(1)
        )
        if previous is not None:
            payload = {**previous.payload, **payload}
            for key in ("delivery_uncertain", "uncertain_recipients", "rejected_recipients"):
                payload.pop(key, None)
    a.delivery_status, a.delivery_error = "pending", None
    await enqueue(db, DELIVERY_JOB, payload, max_attempts=DELIVERY_ATTEMPTS)
    return {"ok": True}


async def _delivery_active(db: AsyncSession, alert_id: int) -> bool:
    from app.db.models import Job

    n = (
        await db.execute(
            select(func.count())
            .select_from(Job)
            .where(
                Job.type == DELIVERY_JOB,
                Job.status.in_(["queued", "running"]),
                Job.payload["alert_id"].as_integer() == alert_id,
            )
        )
    ).scalar_one()
    return int(n) > 0


# --- review queue -------------------------------------------------------------------------------


async def response_notes(db: AsyncSession, message_id: int) -> list[dict[str, Any]]:
    from app.db.models import ReviewResponse

    return [
        {
            "actor": r.actor,
            "choice": r.choice,
            "applied": r.applied,
            "note": r.note,
            "created_at": r.created_at,
        }
        for r in await db.scalars(
            select(ReviewResponse)
            .where(ReviewResponse.message_id == message_id)
            .order_by(ReviewResponse.created_at, ReviewResponse.id)
        )
    ]


class ReviewItem(BaseModel):
    human_feedback: dict[str, Any] | None = None
    response_notes: list[dict[str, Any]] = []
    missing_data: bool = False
    message: MessageOut
    classifications: list[ClassificationOut]


class ReviewPage(BaseModel):
    reviewed_total: int = 0
    items: list[ReviewItem]
    total: int
    page: int
    page_size: int


@router.get("/review")
async def review_queue(
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    view: Literal["pending", "missing_data", "responses", "ai"] = "pending",
) -> ReviewPage:
    from app.db.models import Chat

    reported = exists().where(ReviewDataIssue.message_id == Message.id)
    cond = (
        ai_pending()
        if view == "ai"
        else and_(
            ~ai_pending(),
            (
                exists().where(ReviewFeedback.message_id == Message.id)
                if view == "responses"
                else and_(
                    Message.verdict == "review", reported if view == "missing_data" else ~reported
                )
            ),
        )
    )
    total = int(
        (await db.execute(select(func.count()).select_from(Message).where(cond))).scalar_one()
    )
    rows = (
        await db.execute(
            select(Message, Chat)
            .join(Chat, Chat.id == Message.chat_id)
            .where(cond)
            .order_by(Message.sent_at.desc(), Message.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    kids = await _kids(db, [m.id for m, _ in rows])
    failures = await _failures(db, [m for m, _ in rows])
    items: list[ReviewItem] = []
    for m, c in rows:
        cls = (
            await db.execute(
                select(Classification)
                .where(Classification.message_id == m.id)
                .order_by(Classification.id)
            )
        ).scalars()
        items.append(
            ReviewItem(
                human_feedback=await human_feedback(db, m),
                response_notes=await response_notes(db, m.id),
                missing_data=view == "missing_data",
                message=_to_out(m, c, kids.get(m.id, []), failure=failures.get(m.id)),
                classifications=[
                    ClassificationOut.model_validate(x, from_attributes=True) for x in cls
                ],
            )
        )
    return ReviewPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        reviewed_total=int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ReviewFeedback)
                    .where(ReviewFeedback.verdict.in_(("safe", "harmful")))
                )
            ).scalar_one()
        ),
    )


class ReviewResolution(BaseModel):
    resolution: Literal["safe", "harmful", "ignored"]
    categories: list[str] = Field(default_factory=list, max_length=13)
    explanation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_details(self) -> "ReviewResolution":
        from app.classify.thresholds import DEFAULT_THRESHOLDS

        if set(self.categories) - set(DEFAULT_THRESHOLDS):
            raise ValueError("Unknown review category")
        if self.categories and self.resolution != "harmful":
            raise ValueError("Harm categories require a Harmful decision")
        self.categories = sorted(set(self.categories))
        self.explanation = (self.explanation or "").strip() or None
        return self


async def human_feedback(db: AsyncSession, message: Message) -> dict[str, Any] | None:
    from app.classify.learning import content_hash

    feedback = await db.get(ReviewFeedback, message.id)
    if not feedback:
        return None
    valid = (
        not message.redacted
        and not message.revoked_at
        and feedback.content_hash == content_hash(message)
    )
    return {
        "verdict": feedback.verdict,
        "categories": feedback.categories if valid else [],
        "explanation": feedback.explanation if valid else None,
        "details_current": valid,
    }


@router.post("/review/{message_id}/skip-ai", dependencies=[Depends(parent_user)])
async def skip_ai(message_id: int, db: DB) -> dict[str, Any]:
    """Revoke AI leases atomically, so an in-flight result cannot overwrite human review."""
    m, _ = await _load(db, message_id)
    await db.execute(update(Message).where(Message.id == m.id).values(status=Message.status))
    await db.refresh(m)
    if not await db.scalar(select(Message.id).where(Message.id == m.id, ai_pending())):
        raise HTTPException(409, "Message is no longer waiting for AI")
    await db.execute(
        update(Job)
        .where(
            Job.type == "process_message",
            Job.status.in_(("queued", "running")),
            Job.payload["message_id"].as_integer() == m.id,
        )
        .values(status="cancelled", locked_at=None, last_error="AI skipped for human review")
    )
    feedback = await db.get(ReviewFeedback, m.id)
    m.status, m.verdict = "done", feedback.verdict if feedback else "review"
    m.review_reason = None if feedback else "AI review skipped; human review required"
    await db.commit()
    view = (
        "responses"
        if feedback
        else ("missing_data" if await db.get(ReviewDataIssue, m.id) else "pending")
    )
    return {"ok": True, "human_review_view": view}


@router.post("/review/{message_id}", dependencies=[Depends(parent_user)])
async def resolve_review(
    message_id: int,
    body: ReviewResolution,
    request: Request,
    db: DB,
    cfg: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    m, _ = await _load(db, message_id)
    # Serialize the eligibility check with AI queue changes and parent decisions.
    await db.execute(update(Message).where(Message.id == m.id).values(status=Message.status))
    await db.refresh(m)
    if await db.scalar(select(Message.id).where(Message.id == m.id, ai_pending())):
        raise HTTPException(409, "AI is checking this message; skip AI before deciding")
    if m.verdict != "review" and await db.get(ReviewFeedback, m.id) is None:
        raise HTTPException(status_code=409, detail="Message is not awaiting review")
    import secrets

    from app.alerts.actions import decide
    from app.security.auth import current_user

    user = await current_user(request, db, cfg)
    result = await decide(
        db,
        m,
        body.resolution,
        user.username,
        secrets.token_hex(32),
        request.app.state.session_factory,
        user.id,
        record_audit=False,
        categories=body.categories,
        explanation=body.explanation,
    )
    if not result.get("applied"):
        raise HTTPException(status_code=409, detail=result["note"])
    return {"ok": True, "verdict": result["verdict"], "alert_id": result["alert_id"]}


class ReviewDataReport(BaseModel):
    issue: Literal["missing_data"]


@router.post("/review/{message_id}/data-issue", dependencies=[Depends(parent_user)])
async def report_review_data(message_id: int, body: ReviewDataReport, db: DB) -> dict[str, Any]:
    message, _ = await _load(db, message_id)
    if message.verdict != "review":
        raise HTTPException(status_code=409, detail="Message is not awaiting review")
    if await db.get(ReviewDataIssue, message_id) is None:
        db.add(ReviewDataIssue(message_id=message_id, issue=body.issue))
        await db.commit()
    return {"ok": True, "ignored": True, "issue": body.issue}


@router.get("/review/{message_id}/trace")
async def review_trace(message_id: int, db: DB) -> dict[str, Any]:
    from app.api.messages import get_message
    from app.schedules import redact_error

    detail = await get_message(message_id, db)
    context_ids = {mid for row in detail.classifications for mid in row.context_message_ids or []}
    context = []
    for mid in sorted(context_ids):
        row = await db.get(Message, mid)
        if row:
            context.append(
                {
                    "id": row.id,
                    "sent_at": row.sent_at,
                    "redacted": row.redacted,
                    "text": None if row.redacted else row.text,
                    "transcript": None if row.redacted else row.transcript,
                }
            )
    jobs = []
    for job in await db.scalars(
        select(Job)
        .where(Job.payload["message_id"].as_integer() == message_id)
        .order_by(Job.id.desc())
        .limit(20)
    ):
        jobs.append(
            {
                "id": job.id,
                "type": job.type,
                "status": job.status,
                "attempts": job.attempts,
                "error": await redact_error(db, job.last_error) if job.last_error else None,
            }
        )
    return {
        "trace_kind": "Saved execution trace",
        "message": detail.model_dump(),
        "context": context,
        "jobs": jobs,
        "thresholds": await get_setting(db, "classification.thresholds"),
        "parent_response_notes": await response_notes(db, message_id),
    }
