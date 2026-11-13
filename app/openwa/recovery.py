"""Bounded, resumable catch-up from OpenWA's stored messages, using normal ingestion."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Instance, Setting
from app.ingest.webhooks import _in_scope, _is_alert_loop, _store
from app.openwa.client import OpenWAClient, OpenWAError
from app.openwa.payloads import PayloadError, parse_event
from app.security.crypto import decrypt
from app.settings_store import get_setting


def stored_event(row: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Use the original mapped metadata, with database fields as a conservative fallback."""
    if row.get("sessionId") != session_id:
        raise PayloadError("Stored message belongs to another session")
    metadata = row.get("metadata")
    data = dict(metadata) if isinstance(metadata, dict) else {}
    data.update(
        {
            "id": row.get("waMessageId"),
            "chatId": row.get("chatId"),
            "body": row.get("body"),
            "type": row.get("type"),
            "timestamp": row.get("timestamp"),
            "from": row.get("from"),
            "author": row.get("author"),
            "fromMe": row.get("direction") == "outgoing",
            "isGroup": str(row.get("chatId", "")).endswith("@g.us"),
        }
    )
    if not data.get("media") and row.get("mediaMimetype"):
        data["media"] = {"mimetype": row["mediaMimetype"], "omitted": True}
    if not isinstance(data.get("id"), str) or not isinstance(data.get("chatId"), str):
        raise PayloadError("Stored message has no WhatsApp reference")
    return {"event": "message.sent" if data["fromMe"] else "message.received", "data": data}


async def recover(factory: Any, key_bytes: bytes, *, manual: bool = False) -> dict[str, Any]:
    counts = {
        "accepted": 0,
        "duplicate": 0,
        "skipped": 0,
        "invalid": 0,
        "retry_settings_updated": 0,
        "pages": 0,
    }
    errors: list[dict[str, Any]] = []
    cfg = get_settings()
    async with factory() as db:
        ids = list(await db.scalars(select(Instance.id).order_by(Instance.id)))
    for iid in ids:
        async with factory() as db:
            inst = await db.get(Instance, iid)
            if not inst or not inst.enabled or not inst.openwa_api_key_enc:
                continue
            client = OpenWAClient(inst.openwa_base_url, decrypt(key_bytes, inst.openwa_api_key_enc))
            try:
                counts["retry_settings_updated"] += await client.set_webhook_retries(
                    inst.openwa_instance_id,
                    f"{cfg.webhook_url_base}/webhooks/{inst.webhook_token}",
                    int(await get_setting(db, "openwa.webhook_attempts")),
                )
                roles = await get_setting(db, "phones.roles")
                if (
                    (not manual and not await get_setting(db, "openwa.recovery_enabled"))
                    or roles.get(str(iid)) == "parent"
                    or iid == await get_setting(db, "alerts.sender_instance_id")
                ):
                    continue
                now = datetime.now(UTC)
                hours = int(await get_setting(db, "openwa.recovery_hours"))
                retention = int(await get_setting(db, "retention.message_hours"))
                retention = retention or int(await get_setting(db, "retention.message_days")) * 24
                floor = now - timedelta(hours=min(hours, retention))
                key = f"internal.openwa_recovery.{iid}"
                saved = await db.get(Setting, key)
                state = dict(saved.value) if saved else {}
                if state.get("lookback_hours", hours) != hours:
                    state = {}
                cutoff = max(floor, datetime.fromisoformat(state.get("since", floor.isoformat())))
                cycle_start = state.get("cycle_start") or now.isoformat()
                cursor = state.get("cursor")
                await db.commit()
                for _ in range(3):
                    try:
                        rows = await client.stored_messages(inst.openwa_instance_id, cursor)
                    except OpenWAError as exc:
                        if cursor and exc.status == 400:
                            state.pop("cursor", None)
                            state.pop("cycle_start", None)
                            await _checkpoint(db, key, state)
                        raise
                    counts["pages"] += 1
                    complete = not rows
                    for row in rows:
                        try:
                            created = datetime.fromisoformat(
                                str(row["createdAt"]).replace("Z", "+00:00")
                            )
                            if created.tzinfo is None:
                                raise ValueError("Missing timezone")
                            if created < cutoff:
                                complete = True
                                break
                            message = parse_event(stored_event(row, inst.openwa_instance_id))
                        except (PayloadError, ValueError, KeyError, TypeError, OverflowError):
                            counts["invalid"] += 1
                            continue
                        await db.refresh(inst)
                        if not inst.enabled:
                            return {**counts, "errors": errors, "paused": iid}
                        if (
                            (
                                row.get("direction") == "outgoing"
                                and row.get("status") not in {"sent", "delivered", "read"}
                            )
                            or message is None
                            or message.sent_at < floor
                            or not await _in_scope(db, message)
                            or await _is_alert_loop(db, inst, message, key_bytes)
                        ):
                            counts["skipped"] += 1
                            continue
                        counts[await _store(db, iid, inst.kid_name, message)] += 1
                    if len(rows) < 100:
                        complete = True
                    if complete:
                        state = {
                            "since": (
                                datetime.fromisoformat(cycle_start) - timedelta(minutes=2)
                            ).isoformat(),
                            "last_completed_at": datetime.now(UTC).isoformat(),
                            "lookback_hours": hours,
                        }
                    else:
                        cursor = rows[-1].get("id")
                        if not isinstance(cursor, str) or not cursor:
                            raise OpenWAError(502, "Stored-message page has no cursor")
                        state = {
                            **state,
                            "since": cutoff.isoformat(),
                            "cursor": cursor,
                            "cycle_start": cycle_start,
                            "lookback_hours": hours,
                        }
                    await _checkpoint(db, key, state)
                    if complete:
                        break
            except OpenWAError as exc:
                # Never copy upstream error text, URLs, or message bodies into schedule history.
                await db.rollback()
                errors.append(
                    {
                        "instance_id": iid,
                        "status": exc.status,
                        "error": "OpenWA catch-up unavailable; will retry",
                    }
                )
            finally:
                await client.aclose()
    return {**counts, "errors": errors}


async def _checkpoint(db: Any, key: str, state: dict[str, Any]) -> None:
    row = await db.get(Setting, key)
    if row:
        row.value = state
    else:
        db.add(Setting(key=key, value=state))
    await db.commit()
