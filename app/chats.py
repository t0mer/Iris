"""Group names. OpenWA webhooks carry only a group's ID, so names come from its API."""

import time

from loguru import logger
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Alert, Chat, ChatInstance, Instance, Message
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt

RETRY_AFTER = 300.0  # seconds before asking again about a group whose lookup failed
_last_try: dict[int, float] = {}


async def resolve_group_names(
    factory: async_sessionmaker[AsyncSession], key_bytes: bytes, chat_id: int | None = None
) -> int:
    """Fill in the name of group chats that have none. Best effort: a failure leaves the name empty
    (the portal shows "Unnamed group") and is retried after a pause. Returns how many were named."""
    named = 0
    async with factory() as db:
        stmt = select(Chat).where(
            Chat.is_group.is_(True), or_(Chat.name.is_(None), Chat.name == "")
        )
        if chat_id is not None:
            stmt = stmt.where(Chat.id == chat_id)
        for chat in (await db.execute(stmt)).scalars().all():
            if time.monotonic() - _last_try.get(chat.id, -RETRY_AFTER) < RETRY_AFTER:
                continue
            _last_try[chat.id] = time.monotonic()
            inst = (
                await db.execute(
                    select(Instance)
                    .join(ChatInstance, ChatInstance.instance_id == Instance.id)
                    .where(
                        ChatInstance.chat_id == chat.id,
                        Instance.enabled.is_(True),
                        Instance.openwa_api_key_enc.is_not(None),
                    )
                    .order_by(Instance.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if inst is None or not inst.openwa_api_key_enc:
                continue
            client = OpenWAClient(inst.openwa_base_url, decrypt(key_bytes, inst.openwa_api_key_enc))
            try:
                name = await client.get_group_name(inst.openwa_instance_id, chat.wa_chat_id)
            except OpenWAError as exc:
                logger.debug("group name lookup for chat {} failed: {}", chat.id, exc.message)
                continue
            finally:
                await client.aclose()
            if not name:
                continue
            chat.name = name
            # Alerts snapshot the chat name: update the ones made before the name was known.
            await db.execute(
                update(Alert)
                .where(
                    Alert.message_id.in_(select(Message.id).where(Message.chat_id == chat.id)),
                    or_(Alert.chat_name.is_(None), Alert.chat_name == chat.wa_chat_id),
                )
                .values(chat_name=name)
            )
            await db.commit()
            _last_try.pop(chat.id, None)
            named += 1
    if named:
        logger.info("named {} group chat(s)", named)
    return named
