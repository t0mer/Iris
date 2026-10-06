"""/api/messages: search, detail and in-chat context."""

import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Chat,
    Classification,
    Instance,
    Job,
    Message,
    MessageReceipt,
    MessageRevision,
)
from app.deps import get_db
from app.jobs.queue import has_active_job
from app.security.auth import current_user

router = APIRouter(prefix="/api/messages", tags=["messages"], dependencies=[Depends(current_user)])
DB = Annotated[AsyncSession, Depends(get_db)]

# FTS snippet markers (control chars, never HTML): the UI splits on them, so content is
# never rendered as markup.
MARK_START, MARK_END = "\x02", "\x03"
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_FTS_LIMIT = 5000


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
    classifications: list[ClassificationOut]
    revisions: list[RevisionOut]  # earlier wordings, original first; empty when redacted


def fts_query(q: str) -> str | None:
    """User text -> safe FTS5 query: every word is a quoted prefix term (AND)."""
    tokens = _TOKEN.findall(q)
    return " ".join(f'"{t}"*' for t in tokens) or None


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
        select(func.json_extract(Job.payload, "$.message_id"), Job.last_error)
        .where(
            Job.status.in_(["failed", "dead"]),
            func.json_extract(Job.payload, "$.message_id").in_(ids),
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
        redacted=m.redacted,
        edited_at=m.edited_at,
        revoked_at=m.revoked_at,
        kids=kids,
        failure=failure,
    )


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
    conds: list[ColumnElement[bool]] = []
    snippets: dict[int, str] = {}
    if q and not fts_query(q):
        conds.append(Message.id.in_([]))  # punctuation-only search matches nothing
    elif q and (match := fts_query(q)):
        rows = await db.execute(
            text(
                "SELECT rowid, snippet(messages_fts, -1, :a, :b, '…', 14) FROM messages_fts "
                "WHERE messages_fts MATCH :m ORDER BY rank LIMIT :lim"
            ),
            {"a": MARK_START, "b": MARK_END, "m": match, "lim": _FTS_LIMIT},
        )
        snippets = {int(r[0]): str(r[1]) for r in rows}
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
    return MessageDetail(
        **base.model_dump(),
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


@router.post("/{message_id}/reprocess")
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
