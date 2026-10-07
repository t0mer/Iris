"""POST /webhooks/{token}: validate, normalize, store, enqueue, return 200 fast.

Never calls external APIs: all slow work happens in the job workers.
"""

import asyncio
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.format import is_own_alert
from app.api.instances import webhook_secret
from app.config import Settings, get_settings
from app.db.models import Chat, ChatInstance, Instance, Job, Message, MessageReceipt
from app.deps import get_db
from app.ingest.changes import apply_change
from app.metrics import WEBHOOKS
from app.openwa.payloads import (
    CHANGE_EVENTS,
    IncomingMessage,
    MessageChange,
    PayloadError,
    parse_change,
    parse_event,
)
from app.settings_store import get_setting

router = APIRouter()
# One process: serialising the lookup+insert makes cross-instance dedupe race-free even for
# direct chats, where the two copies of a message live in different chat rows.
_STORE_LOCK = asyncio.Lock()

# Media is normally referenced, but OpenWA inlines small files as base64.
MAX_BODY_BYTES = 25 * 1024 * 1024
_ID_RE = re.compile(r"^(\d+)")


def _id_digits(wa_id: str | None) -> str | None:
    """Digits of a WhatsApp id (`972...@c.us`, `1234@lid`, `1234:59@lid`) or a bare phone."""
    m = _ID_RE.match((wa_id or "").lstrip("+").strip())
    return m.group(1) if m else None


async def _is_alert_loop(
    db: AsyncSession, inst: Instance, msg: IncomingMessage, key_bytes: bytes
) -> bool:
    """Skip Iris's own alerts so they are never classified (and never alert again).

    Recognised by the HMAC-signed link in the text, on ANY instance: the alert recipient may
    itself be a monitored number. A look-alike typed by someone else has no valid signature.
    """
    if is_own_alert(msg.text or "", key_bytes):
        logger.info("instance {} skipped one of Iris's own alert messages", inst.id)
        return True
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    if sender_id != inst.id:
        return False
    recipient = _id_digits(await get_setting(db, "alerts.recipient"))
    return recipient is not None and recipient == _id_digits(msg.wa_chat_id)


async def _in_scope(db: AsyncSession, msg: IncomingMessage) -> bool:
    if msg.from_me and not await get_setting(db, "scope.monitor_from_me"):
        return False
    key = "scope.monitor_groups" if msg.is_group else "scope.monitor_direct"
    return bool(await get_setting(db, key))


def _media_ref(inst_id: int, msg: IncomingMessage) -> dict[str, Any]:
    assert msg.media is not None
    return {
        "instance_id": inst_id,
        "chat_id": msg.wa_chat_id,
        "message_ref": msg.wa_message_ref,
        "mimetype": msg.media.mimetype,
        "filename": msg.media.filename,
        "size_bytes": msg.media.size_bytes,
    }


def _remember_media_ref(message: Message, inst_id: int, msg: IncomingMessage) -> None:
    """Keep the other session's way to fetch the media: it may be the only one OpenWA can serve."""
    if not msg.media:
        return
    ref = _media_ref(inst_id, msg)
    current = message.media
    if not isinstance(current, dict) or not current.get("message_ref"):
        message.media = ref
        return
    known = [current, *current.get("alternates", [])]
    if any(k.get("instance_id") == inst_id for k in known if isinstance(k, dict)):
        return
    message.media = {**current, "alternates": [*current.get("alternates", []), ref]}


async def _store_once(db: AsyncSession, inst_id: int, kid_name: str, msg: IncomingMessage) -> str:
    # The message hash is identical for everyone who sees the message, but in a DIRECT chat each
    # monitored session sees the other party under its own chat id. So dedupe on the hash alone:
    # a message between two monitored kids is one message with two receipts, not two copies.
    existing = (
        await db.execute(select(Message).where(Message.wa_message_id == msg.wa_message_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        if await db.get(ChatInstance, (existing.chat_id, inst_id)) is None:
            db.add(ChatInstance(chat_id=existing.chat_id, instance_id=inst_id))
        if await db.get(MessageReceipt, (existing.id, inst_id)) is None:
            db.add(MessageReceipt(message_id=existing.id, instance_id=inst_id))
        if msg.from_me and not existing.from_me:
            # The sender's own session reported it: the author is a monitored kid.
            existing.from_me, existing.sender_name = True, kid_name
        _remember_media_ref(existing, inst_id, msg)
        await db.commit()
        return "duplicate"

    chat = (
        await db.execute(select(Chat).where(Chat.wa_chat_id == msg.wa_chat_id))
    ).scalar_one_or_none()
    if chat is None:
        chat = Chat(wa_chat_id=msg.wa_chat_id, is_group=msg.is_group)
        db.add(chat)
        await db.flush()
    if chat.name is None and not msg.is_group and not msg.from_me:
        chat.name = msg.sender_name  # direct chat: named after the other party
    if await db.get(ChatInstance, (chat.id, inst_id)) is None:
        db.add(ChatInstance(chat_id=chat.id, instance_id=inst_id))

    media = _media_ref(inst_id, msg) if msg.media else None
    message = Message(
        wa_message_id=msg.wa_message_id,
        chat_id=chat.id,
        sender_wa_id=msg.sender_wa_id,
        sender_name=kid_name if msg.from_me else msg.sender_name,
        from_me=msg.from_me,
        type=msg.type,
        text=msg.text,
        quoted_wa_message_id=msg.quoted_wa_message_id,
        sent_at=msg.sent_at,
        status="pending",
        media=media,
    )
    db.add(message)
    await db.flush()
    db.add(MessageReceipt(message_id=message.id, instance_id=inst_id))
    db.add(Job(type="process_message", payload={"message_id": message.id}))
    await db.commit()
    return "accepted"


async def _store(db: AsyncSession, inst_id: int, kid_name: str, msg: IncomingMessage) -> str:
    """Store a message; two instances racing on the same new chat/message retry as duplicates."""
    for _ in range(3):
        try:
            async with _STORE_LOCK:
                return await _store_once(db, inst_id, kid_name, msg)
        except IntegrityError:
            await db.rollback()  # the other delivery won: the retry then sees its rows
    raise HTTPException(status_code=503, detail="could not store message")


async def _read_capped(request: Request) -> bytes:
    """Read the body with a running cap, so chunked requests cannot buffer unbounded data."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/webhooks/{token}")
async def receive(
    token: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    inst = (
        await db.execute(select(Instance).where(Instance.webhook_token == token))
    ).scalar_one_or_none()
    # Unknown or disabled: same 404, so the response never reveals which.
    if inst is None or not inst.enabled:
        WEBHOOKS.labels("unknown", "rejected").inc()
        raise HTTPException(status_code=404)
    inst_id, kid_name = inst.id, inst.kid_name
    logger.debug("webhook for instance {} (token {}...)", inst_id, token[:6])

    raw = await _read_capped(request)

    sig = request.headers.get("x-openwa-signature")
    if sig is None and inst.signature_required:
        WEBHOOKS.labels(str(inst_id), "rejected").inc()
        raise HTTPException(status_code=401, detail="signature required")
    if sig is not None:
        expected = (
            "sha256="
            + hmac.new(webhook_secret(settings, token).encode(), raw, hashlib.sha256).hexdigest()
        )
        if not hmac.compare_digest(sig, expected):
            WEBHOOKS.labels(str(inst_id), "rejected").inc()
            raise HTTPException(status_code=401, detail="bad signature")

    change: MessageChange | None = None
    try:
        body = json.loads(raw)
        msg = parse_event(body) if isinstance(body, dict) else None
        if isinstance(body, dict) and body.get("event") in CHANGE_EVENTS:
            change = parse_change(body)
    except (ValueError, PayloadError) as exc:
        # 200 so OpenWA does not retry a payload we can never parse.
        logger.warning("unparseable webhook for instance {}: {}", inst_id, exc.__class__.__name__)
        WEBHOOKS.labels(str(inst_id), "rejected").inc()
        return {"result": "rejected"}

    inst.last_webhook_at = datetime.now(UTC)
    if change is not None:
        async with _STORE_LOCK:
            result = await apply_change(db, change)
            await db.commit()  # keeps last_webhook_at even when the change was a no-op
        WEBHOOKS.labels(str(inst_id), result).inc()  # edited | revoked | duplicate | ignored
        return {"result": result}
    if msg is None:
        await db.commit()
        WEBHOOKS.labels(str(inst_id), "skipped").inc()
        return {"result": "ignored"}
    if await _is_alert_loop(db, inst, msg, settings.key_bytes) or not await _in_scope(db, msg):
        await db.commit()
        WEBHOOKS.labels(str(inst_id), "skipped").inc()
        return {"result": "skipped"}
    result = await _store(db, inst_id, kid_name, msg)
    WEBHOOKS.labels(str(inst_id), result).inc()  # accepted | duplicate
    return {"result": result}
