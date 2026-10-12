"""Import optional deployment defaults once; portal settings take precedence afterward."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.recipients import recipients
from app.config import Settings
from app.db.models import Setting
from app.security.crypto import encrypt
from app.security.two_factor import CONFIG_KEY, GREEN_API_KEY, save
from app.settings_store import set_setting


async def bootstrap_notifications(db: AsyncSession, cfg: Settings) -> None:
    defaults: dict[str, str] = {"alerts.channel": cfg.alert_channel}
    if cfg.alert_recipients:
        defaults["alerts.recipient"] = cfg.alert_recipients
    if cfg.telegram_bot_token:
        defaults["alerts.telegram_bot_token"] = cfg.telegram_bot_token
    for key, value in defaults.items():
        if await db.get(Setting, key) is None:
            await set_setting(db, key, value, cfg.key_bytes)
    if (
        cfg.telegram_chat_id
        and cfg.alert_recipients
        and await db.get(Setting, "alerts.recipient_contacts") is None
    ):
        # A shared destination is explicit; parents can replace it with individual chat IDs.
        await set_setting(
            db,
            "alerts.recipient_contacts",
            {
                parent: {"telegram_chat_id": cfg.telegram_chat_id}
                for parent in recipients(cfg.alert_recipients)
            },
        )
    if (
        cfg.greenapi_instance_id
        and cfg.greenapi_token
        and await db.get(Setting, GREEN_API_KEY) is None
    ):
        from app.api.users import WhatsAppBody

        validated = WhatsAppBody(
            api_url=cfg.greenapi_api_url,
            media_url=cfg.greenapi_media_url,
            instance_id=cfg.greenapi_instance_id,
            token=cfg.greenapi_token,
        )
        config = validated.model_dump()
        config["verified"] = False
        await save(db, GREEN_API_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    if cfg.smtp_host and cfg.smtp_password and await db.get(Setting, CONFIG_KEY) is None:
        from app.api.users import SMTPBody

        config = SMTPBody(
            host=cfg.smtp_host,
            port=cfg.smtp_port,
            tls=cfg.smtp_tls,
            username=cfg.smtp_username or "",
            password=cfg.smtp_password,
            sender=cfg.smtp_sender or "",
        ).model_dump()
        config["verified"] = False
        await save(db, CONFIG_KEY, encrypt(cfg.key_bytes, json.dumps(config)), True)
    await db.commit()
