"""/api/messages: search, detail and in-chat context."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.media import MediaOut, media_out
from app.db.models import (
    Alert,
    Chat,
    ChatInstance,
    Classification,
    Instance,
    Job,
    Message,
    MessageReceipt,
    MessageRevision,
    SkippedGroup,
    StoredMedia,
)
from app.db.search import MARK_END, MARK_START, find_matches, search_tokens  # noqa: F401
from app.deps import get_db
from app.jobs.queue import has_active_job
from app.security.auth import current_user, parent_user
from app.settings_store import get_setting

router = APIRouter(prefix="/api/messages", tags=["messages"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/chats/{chat_id}/children")
@router.get("/groups/{chat_id}/children")
async def group_children(chat_id: int, db: DB, request: Request) -> list[dict[str, Any]]:
    chat = await db.get(Chat, chat_id)
    if chat is None or (request.url.path.startswith("/api/messages/groups/") and not chat.is_group):
        raise HTTPException(404, "Group not found")
    rows = await db.execute(
        select(Instance).join(ChatInstance).where(ChatInstance.chat_id == chat_id)
    )
    roles = await get_setting(db, "phones.roles")
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    return [
        {
            "id": i.id,
            "kid_name": i.kid_name,
            "skipped": await db.get(SkippedGroup, (chat_id, i.id)) is not None,
        }
        for i in rows.scalars()
        if roles.get(str(i.id)) != "parent" and i.id != sender_id
    ]


@router.get("/chats/skipped/list")
@router.get("/groups/skipped/list")
async def skipped_groups(db: DB) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Chat, Instance).select_from(SkippedGroup).join(Chat).join(Instance)
    )
    return [
        {
            "is_group": chat.is_group,
            "chat_id": chat.id,
            "chat_name": chat.name or chat.wa_chat_id,
            "instance_id": child.id,
            "kid_name": child.kid_name,
        }
        for chat, child in rows
    ]


class GroupSkipIn(BaseModel):
    skipped: bool = True


@router.put("/chats/{chat_id}/children/{instance_id}", dependencies=[Depends(parent_user)])
@router.put("/groups/{chat_id}/children/{instance_id}", dependencies=[Depends(parent_user)])
async def skip_group(
    chat_id: int, instance_id: int, body: GroupSkipIn, db: DB, request: Request
) -> dict[str, bool]:
    from app.ingest.webhooks import _STORE_LOCK

    async with _STORE_LOCK:
        children = await group_children(chat_id, db, request)
        if instance_id not in {child["id"] for child in children}:
            raise HTTPException(404, "Child is not connected to this group")
        row = await db.get(SkippedGroup, (chat_id, instance_id))
        if body.skipped and row is None:
            db.add(SkippedGroup(chat_id=chat_id, instance_id=instance_id))
        elif not body.skipped and row is not None:
            await db.delete(row)
        await db.commit()
    return {"skipped": body.skipped}


@router.delete(
    "/chats/{chat_id}/children/{instance_id}/history", dependencies=[Depends(parent_user)]
)
@router.delete(
    "/groups/{chat_id}/children/{instance_id}/history", dependencies=[Depends(parent_user)]
)
async def delete_group_history(chat_id: int, instance_id: int, db: DB) -> dict[str, int]:
    from app.ingest.webhooks import _STORE_LOCK

    async with _STORE_LOCK:
        if await db.get(SkippedGroup, (chat_id, instance_id)) is None:
            raise HTTPException(409, "Skip this group for the child before deleting history")
        ids = list(
            (
                await db.scalars(
                    select(Message.id)
                    .join(MessageReceipt)
                    .where(Message.chat_id == chat_id, MessageReceipt.instance_id == instance_id)
                )
            ).all()
        )
        await db.execute(
            delete(MessageReceipt).where(
                MessageReceipt.instance_id == instance_id, MessageReceipt.message_id.in_(ids)
            )
        )
        exclusive = list(
            (
                await db.scalars(
                    select(Message.id).where(
                        Message.id.in_(ids), Message.id.not_in(select(MessageReceipt.message_id))
                    )
                )
            ).all()
        )
        alert_ids = select(Alert.id).where(Alert.message_id.in_(exclusive))
        await db.execute(
            delete(Job).where(
                Job.payload["message_id"].as_integer().in_(exclusive)
                | Job.payload["alert_id"].as_integer().in_(alert_ids)
            )
        )
        await db.execute(
            update(StoredMedia).where(StoredMedia.message_id.in_(exclusive)).values(purge=True)
        )
        await db.execute(delete(Message).where(Message.id.in_(exclusive)))
        # Shared alerts still belong to the children whose receipts remain.
        shared = set(ids) - set(exclusive)
        kids = await _kids(db, list(shared))
        for alert in (await db.scalars(select(Alert).where(Alert.message_id.in_(shared)))).all():
            alert.kid_names = [k.kid_name for k in kids.get(alert.message_id, [])]
        await db.commit()
    return {"removed_receipts": len(ids), "deleted_messages": len(exclusive)}


class KidRef(BaseModel):
    id: int
    kid_name: str


class MessageOut(BaseModel):
    id: int
    chat_id: int
    chat_name: str | None
    is_group: bool
    sender_name: str | None
    from_me: bool
    type: str
    text: str | None
    transcript: str | None
    snippet: str | None
    sent_at: datetime
    status: str
    verdict: str | None
    review_reason: str | None = None
    skip_reason: str | None = None
    raw_type: str | None = None
    diagnostics: dict[str, Any] | None = None
    redacted: bool
    edited_at: datetime | None
    revoked_at: datetime | None
    kids: list[KidRef]
    failure: str | None  # why processing failed (latest failed/dead job), else null


class MessagePage(BaseModel):
    items: list[MessageOut]
    total: int
    page: int
    page_size: int


class ClassificationOut(BaseModel):
    id: int
    stage: str
    input_kind: str
    model: str
    scores: dict[str, Any]
    flagged_categories: list[str]
    band: str
    context_message_ids: list[int] | None
    latency_ms: int | None
    created_at: datetime


class RevisionOut(BaseModel):
    text: str
    replaced_at: datetime


class MessageDetail(MessageOut):
    media: MediaOut | None = None  # a kept copy of the message's media
    classifications: list[ClassificationOut]
    revisions: list[RevisionOut]  # earlier wordings, original first; empty when redacted


async def _kids(db: AsyncSession, ids: list[int]) -> dict[int, list[KidRef]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(MessageReceipt.message_id, Instance.id, Instance.kid_name)
        .join(Instance, Instance.id == MessageReceipt.instance_id)
        .where(MessageReceipt.message_id.in_(ids))
        .order_by(Instance.id)
    )
    out: dict[int, list[KidRef]] = {}
    for mid, iid, name in rows:
        out.setdefault(mid, []).append(KidRef(id=iid, kid_name=name))
    return out


async def _failures(db: AsyncSession, messages: list[Message]) -> dict[int, str]:
    """Latest error of failed/dead jobs, for messages that ended up `failed`."""
    ids = [m.id for m in messages if m.status == "failed"]
    if not ids:
        return {}
    rows = await db.execute(
        select(Job.payload["message_id"].as_integer(), Job.last_error)
        .where(
            Job.status.in_(["failed", "dead"]),
            Job.payload["message_id"].as_integer().in_(ids),
        )
        .order_by(Job.id)
    )
    return {int(mid): err for mid, err in rows if err}  # later jobs overwrite earlier ones


def _to_out(
    m: Message,
    chat: Chat,
    kids: list[KidRef],
    snippet: str | None = None,
    failure: str | None = None,
) -> MessageOut:
    return MessageOut(
        id=m.id,
        chat_id=m.chat_id,
        chat_name=chat.name,
        is_group=chat.is_group,
        sender_name=m.sender_name,
        from_me=m.from_me,
        type=m.type,
        # Redacted content is never exposed (spec 8.5); the row only carries metadata.
        text=None if m.redacted else m.text,
        transcript=None if m.redacted else m.transcript,
        snippet=None if m.redacted else snippet,
        sent_at=m.sent_at,
        status=m.status,
        verdict=m.verdict,
        review_reason=m.review_reason,
        skip_reason=m.skip_reason,
        raw_type=m.raw_type,
        diagnostics=m.diagnostics,
        redacted=m.redacted,
        edited_at=m.edited_at,
        revoked_at=m.revoked_at,
        kids=kids,
        failure=failure,
    )


async def message_filters(
    db: AsyncSession,
    q: str | None = None,
    instance_id: int | None = None,
    chat_id: int | None = None,
    sender: str | None = None,
    type: str | None = None,
    verdict: str | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> tuple[list[ColumnElement[bool]], dict[int, str]]:
    conds: list[ColumnElement[bool]] = []
    snippets: dict[int, str] = {}
    tokens = search_tokens(q) if q else []
    if q and not tokens:
        conds.append(Message.id.in_([]))  # punctuation-only search matches nothing
    elif tokens:
        snippets = await find_matches(db, tokens)
        conds.append(Message.id.in_(list(snippets)))
    if instance_id is not None:
        conds.append(
            Message.id.in_(
                select(MessageReceipt.message_id).where(MessageReceipt.instance_id == instance_id)
            )
        )
    if chat_id is not None:
        conds.append(Message.chat_id == chat_id)
    if sender:
        escaped = sender.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(Message.sender_name.like(f"%{escaped}%", escape="\\"))
    if type:
        conds.append(Message.type == type)
    if verdict:
        conds.append(Message.verdict.is_(None) if verdict == "none" else Message.verdict == verdict)
    if from_:
        conds.append(Message.sent_at >= from_)
    if to:
        conds.append(Message.sent_at <= to)

    return conds, snippets


@router.get("")
async def search_messages(
    db: DB,
    q: str | None = None,
    instance_id: int | None = None,
    chat_id: int | None = None,
    sender: str | None = None,
    type: str | None = None,
    verdict: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> MessagePage:
    conds, snippets = await message_filters(
        db, q, instance_id, chat_id, sender, type, verdict, from_, to
    )

    where = and_(*conds) if conds else None
    count_stmt = select(func.count()).select_from(Message)
    stmt = select(Message, Chat).join(Chat, Chat.id == Message.chat_id)
    if where is not None:
        count_stmt = count_stmt.where(where)
        stmt = stmt.where(where)
    total = int((await db.execute(count_stmt)).scalar_one())
    rows2 = (
        await db.execute(
            stmt.order_by(Message.sent_at.desc(), Message.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    kids = await _kids(db, [m.id for m, _ in rows2])
    failures = await _failures(db, [m for m, _ in rows2])
    return MessagePage(
        items=[
            _to_out(m, c, kids.get(m.id, []), snippets.get(m.id), failures.get(m.id))
            for m, c in rows2
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


async def _load(db: AsyncSession, message_id: int) -> tuple[Message, Chat]:
    row = (
        await db.execute(
            select(Message, Chat)
            .join(Chat, Chat.id == Message.chat_id)
            .where(Message.id == message_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return row[0], row[1]


@router.get("/{message_id}")
async def get_message(message_id: int, db: DB) -> MessageDetail:
    m, chat = await _load(db, message_id)
    cls = (
        await db.execute(
            select(Classification)
            .where(Classification.message_id == m.id)
            .order_by(Classification.id)
        )
    ).scalars()
    base = _to_out(
        m,
        chat,
        (await _kids(db, [m.id])).get(m.id, []),
        failure=(await _failures(db, [m])).get(m.id),
    )
    revisions: list[MessageRevision] = []
    if not m.redacted:
        revisions = list(
            (
                await db.execute(
                    select(MessageRevision)
                    .where(MessageRevision.message_id == m.id)
                    .order_by(MessageRevision.id)
                )
            ).scalars()
        )
    kept = (
        None
        if m.redacted
        else (
            await db.execute(
                select(StoredMedia)
                .where(StoredMedia.message_id == m.id, StoredMedia.purge.is_(False))
                .order_by(StoredMedia.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    )
    return MessageDetail(
        **base.model_dump(),
        media=media_out(kept) if kept is not None else None,
        classifications=[ClassificationOut.model_validate(c, from_attributes=True) for c in cls],
        revisions=[RevisionOut(text=r.text, replaced_at=r.replaced_at) for r in revisions],
    )


@router.get("/{message_id}/context")
async def message_context(
    message_id: int, db: DB, radius: Annotated[int, Query(ge=1, le=50)] = 20
) -> list[MessageOut]:
    """Surrounding messages in the same chat (±radius), oldest first."""
    m, chat = await _load(db, message_id)
    key = (Message.sent_at, Message.id)
    before = (
        (
            await db.execute(
                select(Message)
                .where(
                    Message.chat_id == m.chat_id, Message.id != m.id, Message.sent_at <= m.sent_at
                )
                .order_by(*(k.desc() for k in key))
                .limit(radius)
            )
        )
        .scalars()
        .all()
    )
    after = (
        (
            await db.execute(
                select(Message)
                .where(
                    Message.chat_id == m.chat_id, Message.id != m.id, Message.sent_at > m.sent_at
                )
                .order_by(*(k.asc() for k in key))
                .limit(radius)
            )
        )
        .scalars()
        .all()
    )
    window = sorted([*before, m, *after], key=lambda x: (x.sent_at, x.id))
    kids = await _kids(db, [x.id for x in window])
    failures = await _failures(db, window)
    return [_to_out(x, chat, kids.get(x.id, []), failure=failures.get(x.id)) for x in window]


@router.post("/{message_id}/reprocess", dependencies=[Depends(parent_user)])
async def reprocess_message(message_id: int, db: DB) -> dict[str, bool]:
    """Re-enqueue classification. Blocked for redacted messages (their content is gone)."""
    m, _ = await _load(db, message_id)
    if m.redacted:
        raise HTTPException(status_code=409, detail="Redacted messages cannot be reprocessed")
    if await has_active_job(db, m.id):
        raise HTTPException(status_code=409, detail="Already queued or running")
    m.status, m.verdict = "pending", None
    db.add(Job(type="process_message", payload={"message_id": m.id}))
    await db.commit()
    return {"ok": True}
