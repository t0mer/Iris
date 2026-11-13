"""Test evidence expires when a notification destination or provider changes."""

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Instance
from app.security.two_factor import load, save
from app.settings_store import get_secret, get_setting


async def notifier_fingerprint(db: AsyncSession, channel: str) -> str:
    values = {
        key: await get_setting(db, key)
        for key in ("alerts.recipient", "alerts.recipient_contacts", "alerts.sender_instance_id")
    }
    channels = await get_setting(db, "alerts.recipient_channels")
    if channels:
        values["alerts.recipient_channels"] = channels
    if channel == "telegram":
        values["token"] = await get_secret(
            db, "alerts.telegram_bot_token", get_settings().key_bytes
        )
    if channel == "openwa":
        sender = (
            await db.get(Instance, values["alerts.sender_instance_id"])
            if values["alerts.sender_instance_id"]
            else None
        )
        values["sender"] = (
            [sender.openwa_base_url, sender.openwa_instance_id, sender.openwa_api_key_enc]
            if sender
            else None
        )
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


async def record_notifier_test(db: AsyncSession, channel: str) -> None:
    await save(db, f"internal.notifier_test.{channel}", await notifier_fingerprint(db, channel))


async def notifier_test_passed(db: AsyncSession, channel: str) -> bool:
    return bool(
        await load(db, f"internal.notifier_test.{channel}")
        == await notifier_fingerprint(db, channel)
    )


async def ai_provider_fingerprint(db: AsyncSession, target: str) -> str:
    """Store only a digest; changing saved credentials/models invalidates test evidence."""
    cfg = get_settings()
    values = {
        "target": target,
        "classification": cfg.classification_provider,
        "transcription": cfg.transcription_provider,
        "ollama": [cfg.ollama_base_url, cfg.ollama_model],
        "whisper": [cfg.whisper_url, cfg.whisper_model, cfg.whisper_api_key],
    }
    for key in (
        "classification.model",
        "transcription.provider",
        "transcription.openai_model",
        "transcription.cloudflare_account_id",
        "transcription.cloudflare_model",
    ):
        values[key] = await get_setting(db, key)
    for key in ("openai.api_key", "transcription.cloudflare_api_token"):
        values[key] = await get_secret(db, key, cfg.key_bytes)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


async def ai_provider_status(db: AsyncSession) -> list[dict[str, Any]]:
    cfg = get_settings()
    transcription = cfg.transcription_provider or (
        "local_whisper" if cfg.whisper_url else await get_setting(db, "transcription.provider")
    )
    required = {
        cfg.classification_provider,
        "openai_transcription" if transcription == "openai" else transcription,
    }
    openai = bool(await get_secret(db, "openai.api_key", cfg.key_bytes))
    cloudflare = bool(
        await get_setting(db, "transcription.cloudflare_account_id")
        and await get_secret(db, "transcription.cloudflare_api_token", cfg.key_bytes)
    )
    rows = []
    for target, title, configured in (
        ("ollama", "Ollama classification", bool(cfg.ollama_base_url and cfg.ollama_model)),
        ("ollama_image", "Ollama image capability", bool(cfg.ollama_base_url and cfg.ollama_model)),
        ("openai", "OpenAI classification", openai),
        ("openai_transcription", "OpenAI transcription", openai),
        ("local_whisper", "Local Whisper transcription", bool(cfg.whisper_url)),
        ("cloudflare", "Cloudflare transcription", cloudflare),
    ):
        proof = await load(db, f"internal.ai_test.{target}", {})
        rows.append(
            {
                "id": target,
                "title": title,
                "configured": configured,
                "required": target in required,
                "tested": bool(
                    configured
                    and proof.get("ok")
                    and proof.get("fingerprint") == await ai_provider_fingerprint(db, target)
                ),
                "detail": proof.get("detail")
                if proof.get("fingerprint") == await ai_provider_fingerprint(db, target)
                else None,
            }
        )
    return rows
