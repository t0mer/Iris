"""Durable parent decisions and recipient-bound provider callbacks."""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.readiness import delivery_readiness
from app.config import get_settings
from app.db.models import (
    Alert,
    AlertAction,
    AuditLog,
    Message,
    MessageReceipt,
    ReviewFeedback,
    ReviewResponse,
    Setting,
)
from app.settings_store import get_secret, get_setting

_lock = asyncio.Lock()
CHOICES = {"safe": "SAFE", "harmful": "Harmful", "ignored": "Ignore"}


def provider_key(channel: str, config: dict[str, Any]) -> str:
    identity = str(config.get("instance_id", "")) + ":" + str(config.get("token", ""))
    return hashlib.sha256((channel + ":" + identity).encode()).hexdigest()


async def buttons(
    db: AsyncSession,
    alert_id: int,
    target: str,
    channel: str,
    destination: str,
    config: dict[str, Any],
) -> list[dict[str, str]]:
    if not await get_setting(db, "alerts.review_buttons") or channel not in (
        "telegram",
        "greenapi",
    ):
        return []
    # Personal recipients only: a group member must never decide on behalf of a parent.
    if (channel == "telegram" and (not destination.isdigit() or int(destination) <= 0)) or (
        channel == "greenapi" and not destination.endswith("@c.us")
    ):
        return []
    if not (await db.get(Alert, alert_id)):
        return []
    key = provider_key(channel, config)
    rows = list(
        await db.scalars(
            select(AlertAction).where(
                AlertAction.alert_id == alert_id,
                AlertAction.target == target,
                AlertAction.channel == channel,
                AlertAction.destination == destination,
                AlertAction.provider_key == key,
                AlertAction.expires_at > datetime.now(UTC),
            )
        )
    )
    if not rows:
        for choice in CHOICES:
            row = AlertAction(
                token="iris:" + secrets.token_urlsafe(24),
                alert_id=alert_id,
                target=target,
                destination=destination,
                channel=channel,
                provider_key=key,
                choice=choice,
                expires_at=datetime.now(UTC) + timedelta(days=4),
            )
            db.add(row)
            rows.append(row)
        await db.commit()
    return [{"id": r.token, "text": CHOICES[r.choice]} for r in rows]


async def decide(
    db: AsyncSession,
    message: Message,
    choice: str,
    actor: str,
    event_id: str,
    factory: Any,
    user_id: int | None = None,
    record_audit: bool = True,
    categories: list[str] | None = None,
    explanation: str | None = None,
) -> dict[str, Any]:
    """The unique feedback key arbitrates races; every later response becomes a note."""
    async with _lock:
        if await db.get(ReviewResponse, event_id):
            return {"ok": True, "duplicate": True}
        # Start a real write transaction and lock this message across processes.
        await db.execute(
            update(Message).where(Message.id == message.id).values(verdict=Message.verdict)
        )
        if await db.get(ReviewResponse, event_id):
            await db.commit()
            return {"ok": True, "duplicate": True}
        await db.refresh(message)
        before = message.verdict
        applied = False
        feedback = await db.get(ReviewFeedback, message.id)
        if feedback is None:
            try:
                async with db.begin_nested():
                    from app.classify.learning import content_hash

                    feedback = ReviewFeedback(
                        message_id=message.id,
                        verdict=choice,
                        categories=categories or None,
                        explanation=explanation if not message.redacted else None,
                        content_hash=content_hash(message),
                    )
                    db.add(feedback)
                    await db.flush()
                applied = True
            except IntegrityError:
                feedback = await db.get(ReviewFeedback, message.id)
        assert feedback is not None
        note = (
            f"{actor} chose {CHOICES[choice]}. First response accepted."
            if applied
            else (
                f"{actor} chose {CHOICES[choice]}. Kept the first decision: "
                f"{CHOICES.get(feedback.verdict, feedback.verdict)}."
            )
        )
        db.add(
            ReviewResponse(
                id=event_id,
                message_id=message.id,
                actor=actor,
                choice=choice,
                applied=applied,
                note=note,
            )
        )
        if record_audit:
            db.add(
                AuditLog(
                    user_id=user_id,
                    username=actor,
                    method="POST",
                    path=f"/api/review/{message.id}/response",
                    status_code=200,
                    changes=[
                        {
                            "entity": "Message",
                            "id": str(message.id),
                            "field": "verdict",
                            "before": before,
                            "after": choice if applied else before,
                        },
                        {"note": note},
                    ],
                )
            )
        alert_id = None
        if applied:
            message.verdict, message.review_reason = choice, None
            from app.classify.learning import capture

            await capture(db, message, choice)
            alert = await db.scalar(select(Alert).where(Alert.message_id == message.id))
            if alert:
                alert.status = "acknowledged" if choice == "harmful" else "dismissed"
            if choice == "harmful":
                from app.alerts.service import create_alert, scores_from_classifications

                # create_alert performs the same redaction and media-purge policy as portal review.
                scores = await scores_from_classifications(db, message)
                alert = await create_alert(db, message, scores, confirmed=True)
                alert_id = alert.id
                await db.commit()
                from app.media.keep import keep_media

                cfg = get_settings()
                await keep_media(
                    factory,
                    message.id,
                    list(scores),
                    cfg.key_bytes,
                    cfg.data_dir,
                    f"review-{message.id}",
                )
            elif choice == "safe":
                from app.media.keep import wants
                from app.media.records import mark_purge

                if not wants(str(await get_setting(db, "media.policy")), "safe"):
                    await mark_purge(db, message.id)
        await db.commit()
        return {
            "ok": True,
            "verdict": feedback.verdict,
            "applied": applied,
            "alert_id": alert_id,
            "note": note,
        }


async def accept(
    db: AsyncSession,
    channel: str,
    config: dict[str, Any],
    token: str,
    destination: str,
    actor_id: str,
    event: str,
    factory: Any,
) -> str:
    if not event:
        return "Provider response is missing its message ID."
    row = await db.get(AlertAction, token)
    if not row or row.channel != channel or row.provider_key != provider_key(channel, config):
        return "This response does not belong to Iris."
    if row.expires_at <= datetime.now(UTC):
        return "This button expired. Open Iris to review the message."
    if destination != row.destination or actor_id != destination:
        return "This button belongs to another parent."
    readiness = await delivery_readiness(db, channel)
    recipient = next(
        (
            r
            for r in readiness.recipients
            if r.target == row.target and r.eligible and r.destination == destination
        ),
        None,
    )
    if recipient is None:
        return "This parent is no longer eligible. Check alert recipients in Iris."
    alert = await db.get(Alert, row.alert_id)
    if alert is None:
        return "This alert no longer exists."
    assigned = (await get_setting(db, "alerts.recipient_children")).get(row.target)
    if assigned is not None and not await db.scalar(
        select(MessageReceipt.message_id).where(
            MessageReceipt.message_id == alert.message_id, MessageReceipt.instance_id.in_(assigned)
        )
    ):
        return "This child is no longer assigned to this parent."
    message = await db.get(Message, alert.message_id)
    if message is None:
        return "This message no longer exists."
    event_id = hashlib.sha256((provider_key(channel, config) + ":" + event).encode()).hexdigest()
    result = await decide(
        db, message, row.choice, recipient.name, event_id, factory, recipient.user_id
    )
    return str(result.get("note", "Response already recorded."))


async def poll(factory: Any) -> dict[str, Any]:
    """Bounded FIFO polling, committing responses before acknowledging provider updates."""
    cfg = get_settings()
    async with factory() as db:
        await db.execute(delete(AlertAction).where(AlertAction.expires_at <= datetime.now(UTC)))
        await db.commit()
        if not await get_setting(db, "alerts.review_buttons"):
            return {"skipped": "Review buttons disabled"}
        from app.security.two_factor import green_api_config

        configs = {
            "telegram": {"token": await get_secret(db, "alerts.telegram_bot_token", cfg.key_bytes)},
            "greenapi": await green_api_config(db, cfg),
        }
        channels = set(await db.scalars(select(AlertAction.channel).distinct()))
        processed = 0
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for channel in ("telegram", "greenapi"):
                config = configs[channel]
                if channel not in channels or not config.get("token"):
                    continue
                if not await db.scalar(
                    select(AlertAction.token)
                    .where(
                        AlertAction.channel == channel,
                        AlertAction.provider_key == provider_key(channel, config),
                    )
                    .limit(1)
                ):
                    continue

                async def call(
                    method: str,
                    body: dict[str, Any] | None = None,
                    verb: str = "POST",
                    channel: str = channel,
                    config: dict[str, Any] = config,
                ) -> Any:
                    base = (
                        f"https://api.telegram.org/bot{config['token']}/{method}"
                        if channel == "telegram"
                        else (
                            f"{config['api_url']}/waInstance{config['instance_id']}"
                            f"/{method}/{config['token']}"
                        )
                    )
                    if method == "deleteNotification":
                        assert body is not None
                        base += "/" + str(body["receiptId"])
                    response = await client.request(
                        verb, base, json=body if verb == "POST" else None
                    )
                    if method == "answerCallbackQuery" and response.status_code == 400:
                        # Expired Telegram acknowledgements do not undo a durable decision.
                        return False
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"{channel} response polling rejected (HTTP {response.status_code}). "
                            "Check provider settings and exclusive polling access."
                        )
                    if method == "receiveNotification" and not response.content:
                        return None
                    result = response.json()
                    if method == "deleteNotification" and result.get("result") is not True:
                        raise RuntimeError(
                            "GreenAPI could not acknowledge the response notification."
                        )
                    if channel == "telegram":
                        if result.get("ok") is not True:
                            raise RuntimeError(
                                "Telegram response polling rejected. Check bot configuration."
                            )
                        return result["result"]
                    return result

                if channel == "telegram":
                    info = await call("getWebhookInfo")
                    if info.get("url"):
                        raise RuntimeError(
                            "Telegram bot has a webhook. Use a dedicated bot with no webhook "
                            "for Iris response polling."
                        )
                    state_key = "internal.review_offset." + provider_key(channel, config)
                    state = await db.get(Setting, state_key)
                    offset = state.value if state else 0
                    updates = await call(
                        "getUpdates",
                        {
                            "offset": offset,
                            "limit": 100,
                            "timeout": 0,
                            "allowed_updates": ["callback_query"],
                        },
                    )
                    for update in updates:
                        callback = update.get("callback_query")
                        if callback:
                            chat = callback.get("message", {}).get("chat", {})
                            reply = await accept(
                                db,
                                channel,
                                config,
                                str(callback.get("data", "")),
                                str(chat.get("id", "")),
                                str(callback.get("from", {}).get("id", "")),
                                str(callback["id"]),
                                factory,
                            )
                            await call(
                                "answerCallbackQuery",
                                {"callback_query_id": callback["id"], "text": reply[:200]},
                            )
                            processed += 1
                        if state is None:
                            state = Setting(key=state_key, value=int(update["update_id"]) + 1)
                            db.add(state)
                        else:
                            state.value = int(update["update_id"]) + 1
                        await db.commit()
                else:
                    info = await call("getSettings", verb="GET")
                    if info.get("webhookUrl"):
                        raise RuntimeError(
                            "GreenAPI instance has a webhook. Use a dedicated instance "
                            "with no webhook "
                            "for Iris response polling."
                        )
                    if info.get("incomingWebhook") != "yes":
                        raise RuntimeError(
                            "Enable GreenAPI incoming message notifications "
                            "to receive review button responses."
                        )
                    for _ in range(50):
                        notification = await call("receiveNotification", verb="GET")
                        if not notification:
                            break
                        body = notification["body"]
                        data = body.get("messageData", {})
                        selection = data.get(
                            "templateButtonReplyMessage", data.get("buttonsResponseMessage", {})
                        )
                        token = selection.get("selectedId", selection.get("selectedButtonId", ""))
                        if body.get("typeWebhook") == "incomingMessageReceived" and token:
                            sender = body.get("senderData", {})
                            await accept(
                                db,
                                channel,
                                config,
                                str(token),
                                str(sender.get("chatId", "")),
                                str(sender.get("sender", "")),
                                str(body.get("idMessage", "")),
                                factory,
                            )
                            processed += 1
                        await call(
                            "deleteNotification",
                            {"receiptId": notification["receiptId"]},
                            verb="DELETE",
                        )
        return {"responses_checked": processed}
