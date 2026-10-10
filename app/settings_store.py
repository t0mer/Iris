"""Runtime settings in the `settings` table: a typed registry with defaults and validation.

Secrets are AES-256-GCM encrypted at rest and never returned by the API (only `{"set": bool}`).
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.recipients import recipients, validate_recipients
from app.classify.thresholds import validate_thresholds
from app.config import validate_public_base_url
from app.db.models import Setting
from app.media.s3 import validate_endpoint
from app.security.crypto import decrypt, encrypt
from app.transcription.cloudflare import validate_account_id, validate_model


@dataclass(frozen=True)
class Spec:
    default: Any
    validate: Callable[[Any], Any]
    secret: bool = False


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError("must be true or false")
    return v


def _str(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("must be a non-empty string")
    return v.strip()


def _opt_str(v: Any) -> str | None:
    return None if v is None or v == "" else _str(v)


def _similarity(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise ValueError("must be a number between 0 and 1")
    if not 0 <= v <= 1:
        raise ValueError("must be a number between 0 and 1")
    return float(v)


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("must be an integer")
    return v


def _int_range(lo: int, hi: int) -> Callable[[Any], int]:
    def check(v: Any) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"must be an integer between {lo} and {hi}")
        return v

    return check


def _cf_account(v: Any) -> str | None:
    return None if v is None or v == "" else validate_account_id(_str(v))


def _opt_secret(v: Any) -> str | None:
    return None if v is None or v == "" else _str(v)  # empty/null clears the secret


def _thresholds(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("must be an object of {category: {low, high}}")
    return {c: {"low": lo, "high": hi} for c, (lo, hi) in validate_thresholds(v).items()}


def _timezone(v: Any) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = _str(v)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError("unknown timezone (use an IANA name like Asia/Jerusalem)") from exc
    return name


def _choice(*options: str) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        if v not in options:
            raise ValueError(f"must be one of: {', '.join(options)}")
        return str(v)

    return check


def _s3_endpoint(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return validate_endpoint(_str(v))


def _bucket(v: Any) -> str | None:
    if v is None or v == "":
        return None
    name = _str(v)
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]", name):
        raise ValueError("use 3-63 lowercase letters, digits, dots or hyphens")
    return name


def _prefix(v: Any) -> str:
    if v is None or v == "":
        return ""
    text = _str(v).lstrip("/")
    if not re.fullmatch(r"[A-Za-z0-9._\-/]{1,200}", text) or ".." in text.split("/"):
        raise ValueError("use letters, digits, dots, hyphens and slashes")
    return text if text.endswith("/") else text + "/"


def _provider_url(v: Any) -> str | None:
    import ipaddress
    from urllib.parse import urlsplit

    value = _opt_str(v)
    if value is None:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("use an http or https endpoint")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("credentials belong in the API key field, not the URL")
        _ = parts.port
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            address = None
        if address and (address.is_link_local or address.is_unspecified or address.is_multicast):
            raise ValueError("endpoint address is not allowed")
    except ValueError as exc:
        raise ValueError("invalid provider endpoint") from exc
    return value.rstrip("/")


RUNTIME_FIELDS = (
    "public_base_url",
    "webhook_base_url",
    "classification_provider",
    "ollama_base_url",
    "ollama_model",
    "transcription_provider",
    "whisper_url",
    "whisper_model",
    "whisper_fallback_model",
    "local_safety_mode",
    "workers",
    "delivery_workers",
    "job_heartbeat_seconds",
    "monitoring_silence_minutes",
    "require_webhook_signatures",
)


def _phone_roles(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not key.isdigit() or role not in ("child", "parent")
        for key, role in value.items()
    ):
        raise ValueError("phone roles must map instance IDs to child or parent")
    return dict(value)


def _timestamp(value: Any) -> str | None:
    value = _opt_str(value)
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _recipient_children(value: Any) -> dict[str, list[int]]:
    if not isinstance(value, dict):
        raise ValueError("must map parent numbers to child ID lists")
    clean = {}
    for parent, children in value.items():
        targets = recipients(parent) if isinstance(parent, str) else []
        if (
            len(targets) != 1
            or not isinstance(children, list)
            or any(
                isinstance(child, bool) or not isinstance(child, int) or child < 1
                for child in children
            )
        ):
            raise ValueError("each parent needs one valid number and positive child IDs")
        clean[targets[0]] = sorted(set(children))
    return clean


def _recipient_contacts(value: Any) -> dict[str, dict[str, str]]:
    from app.security.two_factor import email_address

    if not isinstance(value, dict):
        raise ValueError("must map parent numbers to notification contacts")
    clean = {}
    for parent, contact in value.items():
        targets = recipients(parent) if isinstance(parent, str) else []
        if len(targets) != 1 or not isinstance(contact, dict):
            raise ValueError("invalid parent notification contact")
        if set(contact) - {"email", "telegram_chat_id"}:
            raise ValueError("unknown contact field")
        result = {}
        if contact.get("email") and not isinstance(contact["email"], str):
            raise ValueError("Email must be a string")
        if contact.get("email"):
            result["email"] = str(email_address(contact["email"]))
        if contact.get("telegram_chat_id"):
            chat_id = str(contact["telegram_chat_id"])
            if not re.fullmatch(r"-?[0-9]{1,20}", chat_id):
                raise ValueError("Telegram chat ID must be numeric")
            result["telegram_chat_id"] = chat_id
        clean[targets[0]] = result
    return clean


def _telegram_token(value: Any) -> str | None:
    value = _opt_secret(value)
    if value and not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", value):
        raise ValueError("Enter a Telegram bot token from BotFather")
    return str(value) if value is not None else None


def _schedules(value: Any) -> dict[str, Any]:
    from app.schedules import CATALOG

    if not isinstance(value, dict):
        raise ValueError("Schedules must be an object")
    clean = {}
    for key, config in value.items():
        if key not in CATALOG or not isinstance(config, dict):
            raise ValueError("Unknown schedule")
        recovery_fields = {"retry_count", "retry_wait_minutes", "notify_wait_minutes"}
        allowed = {"enabled", "interval", "time"} | (
            recovery_fields if key == "connections" else set()
        )
        if set(config) - allowed:
            raise ValueError("Unknown schedule option")
        result: dict[str, Any] = {}
        if "enabled" in config:
            result["enabled"] = _bool(config["enabled"])
        if "interval" in config:
            if CATALOG[key]["interval"] is None:
                raise ValueError("This schedule does not use an interval")
            result["interval"] = _int_range(15, 86400)(config["interval"])
        if "time" in config:
            if (
                key != "daily_summary"
                or not isinstance(config["time"], str)
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", config["time"])
            ):
                raise ValueError("Daily summary time must be HH:MM")
            result["time"] = config["time"]
        for field in recovery_fields:
            if field in config:
                result[field] = _int_range(
                    0 if field == "retry_count" else 1, 10 if field == "retry_count" else 1440
                )(config[field])
        clean[key] = result
    return clean


def _recipient_channels(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("must map parent recipients to alert channels")
    clean = {}
    for parent, channel in value.items():
        targets = recipients(parent) if isinstance(parent, str) else []
        if len(targets) != 1:
            raise ValueError("invalid parent recipient")
        clean[targets[0]] = _choice("openwa", "telegram", "smtp", "greenapi")(channel)
    return clean


REGISTRY: dict[str, Spec] = {
    "openwa.webhook_attempts": Spec(3, _int_range(1, 5)),
    "openwa.recovery_enabled": Spec(True, _bool),
    "openwa.recovery_hours": Spec(24, _int_range(1, 720)),
    "schedules.config": Spec({}, _schedules),
    "runtime.webhook_base_url": Spec(
        None, lambda v: None if v is None or v == "" else validate_public_base_url(_str(v))
    ),
    "runtime.public_base_url": Spec(
        None, lambda v: None if v is None else validate_public_base_url(_str(v))
    ),
    "phones.roles": Spec({}, _phone_roles),
    "phones.session_names": Spec(
        {}, lambda value: {str(int(k)): str(v)[:100] for k, v in dict(value or {}).items()}
    ),
    "runtime.classification_provider": Spec(
        None, lambda v: None if v is None else _choice("openai", "ollama")(v)
    ),
    "runtime.transcription_provider": Spec(
        None, lambda v: None if v is None else _choice("openai", "cloudflare", "local_whisper")(v)
    ),
    "runtime.ollama_base_url": Spec(None, _provider_url),
    "runtime.ollama_model": Spec(None, _opt_str),
    "runtime.whisper_url": Spec(None, _provider_url),
    "runtime.whisper_model": Spec(None, _opt_str),
    "runtime.whisper_fallback_model": Spec(None, lambda v: None if v is None else str(v).strip()),
    "runtime.whisper_api_key": Spec(None, _opt_secret, secret=True),
    "runtime.whisper_use_environment_key": Spec(True, _bool),
    "runtime.local_safety_mode": Spec(None, lambda v: None if v is None else _bool(v)),
    "runtime.require_webhook_signatures": Spec(None, lambda v: None if v is None else _bool(v)),
    "runtime.workers": Spec(None, lambda v: None if v is None else _int_range(0, 16)(v)),
    "runtime.delivery_workers": Spec(None, lambda v: None if v is None else _int_range(0, 4)(v)),
    "runtime.job_heartbeat_seconds": Spec(
        None, lambda v: None if v is None else _int_range(0, 120)(v)
    ),
    "runtime.monitoring_silence_minutes": Spec(
        None, lambda v: None if v is None else _int_range(0, 10080)(v)
    ),
    "transcription.provider": Spec("openai", _choice("openai", "cloudflare")),
    "transcription.openai_model": Spec(
        "gpt-4o-mini-transcribe", _choice("gpt-4o-mini-transcribe", "whisper-1")
    ),
    "transcription.cloudflare_account_id": Spec(None, _cf_account),
    "transcription.cloudflare_api_token": Spec(None, _opt_secret, secret=True),
    "transcription.cloudflare_model": Spec(
        "@cf/openai/whisper-large-v3-turbo", lambda v: validate_model(_str(v))
    ),
    "openai.api_key": Spec(None, _opt_secret, secret=True),
    "classification.model": Spec("omni-moderation-latest", _str),
    "classification.learning_mode": Spec("off", _choice("off", "shadow", "active")),
    "classification.community_learning": Spec(False, _bool),
    "classification.learning_retrieval": Spec("lexical", _choice("lexical", "semantic")),
    "classification.learning_embedding_model": Spec(None, _opt_str),
    "classification.learning_min_similarity": Spec(0.7, _similarity),
    "classification.thresholds": Spec({}, _thresholds),
    "classification.context_window_size": Spec(8, _int_range(1, 20)),
    "classification.context_max_age_hours": Spec(6, _int_range(1, 168)),
    "scope.monitor_from_me": Spec(True, _bool),
    "scope.monitor_direct": Spec(True, _bool),
    "scope.monitor_groups": Spec(True, _bool),
    "retention.message_hours": Spec(0, _int_range(0, 87600)),
    "media.retention_hours": Spec(0, _int_range(0, 87600)),
    "retention.message_days": Spec(90, _int_range(1, 3650)),
    "retention.alert_days": Spec(365, _int_range(1, 3650)),
    "alerts.sender_instance_id": Spec(None, _opt_int),
    "alerts.recipient": Spec(None, lambda v: validate_recipients(_opt_str(v))),
    "alerts.system_recipient": Spec(None, lambda v: validate_recipients(_opt_str(v))),
    "alerts.system_contacts": Spec({}, _recipient_contacts),
    "auth.default_channel": Spec("email", _choice("email", "whatsapp")),
    "alerts.channel": Spec("openwa", _choice("openwa", "telegram", "smtp", "greenapi")),
    "alerts.provider_notification_minutes": Spec(60, _int_range(60, 10080)),
    "alerts.provider_notification_channel": Spec(
        "mixed", _choice("mixed", "openwa", "telegram", "smtp", "greenapi")
    ),
    "alerts.recipient_contacts": Spec({}, _recipient_contacts),
    "alerts.recipient_channels": Spec({}, _recipient_channels),
    "alerts.telegram_bot_token": Spec(None, _telegram_token, secret=True),
    "alerts.recipient_children": Spec({}, _recipient_children),
    "alerts.review_notify_since": Spec(None, _timestamp),
    "alerts.review_buttons": Spec(False, _bool),
    "alerts.notification_style": Spec("summary", _choice("summary", "detailed")),
    "alerts.send_interval_seconds": Spec(30, _int_range(5, 3600)),
    "alerts.send_hourly_limit": Spec(60, _int_range(1, 1000)),
    "alerts.send_daily_limit": Spec(250, _int_range(1, 10000)),
    "alerts.cooldown_minutes": Spec(10, _int_range(0, 1440)),
    "alerts.alert_on_review": Spec(True, _bool),
    "alerts.notify_changes": Spec(True, _bool),
    "alerts.timezone": Spec("Asia/Jerusalem", _timezone),
    "media.policy": Spec("off", _choice("off", "harmful", "harmful_review", "all")),
    "media.backend": Spec("local", _choice("local", "s3")),
    "media.s3_endpoint": Spec(None, _s3_endpoint),
    "media.s3_bucket": Spec(None, _bucket),
    "media.s3_region": Spec("auto", _str),
    "media.s3_access_key": Spec(None, _opt_str),
    "media.s3_secret_key": Spec(None, _opt_secret, secret=True),
    "media.s3_prefix": Spec("iris/", _prefix),
    "media.s3_path_style": Spec(True, _bool),
    "media.retention_days": Spec(30, _int_range(1, 3650)),
    "media.recovery_attempts": Spec(1, _int_range(0, 3)),
    "media.recovery_wait_seconds": Spec(5, _int_range(0, 30)),
}


def _spec(key: str) -> Spec:
    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown setting: {key}") from None


async def get_setting(db: AsyncSession, key: str) -> Any:
    """Plain (non-secret) value, or the default."""
    spec = _spec(key)
    if spec.secret:
        raise ValueError(f"{key} is a secret: use get_secret")
    row = await db.get(Setting, key)
    return row.value if row is not None else spec.default


async def get_secret(db: AsyncSession, key: str, key_bytes: bytes) -> str | None:
    if not _spec(key).secret:
        raise ValueError(f"{key} is not a secret")
    row = await db.get(Setting, key)
    return decrypt(key_bytes, row.value) if row is not None and row.value else None


async def set_setting(
    db: AsyncSession, key: str, value: Any, key_bytes: bytes | None = None
) -> None:
    """Validate and store. Secrets need `key_bytes` and are encrypted before storage."""
    spec = _spec(key)
    clean = spec.validate(value)
    row = await db.get(Setting, key)
    if spec.secret:
        if key_bytes is None:
            raise ValueError("secret settings need an encryption key")
        if clean is None:  # clearing a secret removes it
            if row is not None:
                await db.delete(row)
                await db.commit()
            return
        clean = encrypt(key_bytes, clean)
    if row is None:
        db.add(Setting(key=key, value=clean, is_secret=spec.secret))
    else:
        row.value, row.is_secret = clean, spec.secret
    await db.commit()


async def all_settings(db: AsyncSession) -> dict[str, Any]:
    """Every setting for the API: secrets are reported as {"set": bool}, never as values."""
    rows = {r.key: r for r in (await db.execute(select(Setting))).scalars()}
    out: dict[str, Any] = {}
    for key, spec in REGISTRY.items():
        row = rows.get(key)
        if spec.secret:
            out[key] = {"set": bool(row and row.value)}
        else:
            out[key] = row.value if row is not None else spec.default
    return out


async def reload_runtime_settings(db: AsyncSession) -> None:
    """Database overrides are explicit; absent rows preserve environment/base defaults."""
    from app.config import Settings, get_settings

    # Build off-cache so no job can observe half-applied overrides or a temporary cloud default.
    cfg = Settings()
    for field in RUNTIME_FIELDS:
        value = await get_setting(db, "runtime." + field)
        if value is not None:
            setattr(cfg, field, value)
    local_key = await get_secret(db, "runtime.whisper_api_key", cfg.key_bytes)
    if local_key:
        cfg.whisper_api_key = local_key
    elif not await get_setting(db, "runtime.whisper_use_environment_key"):
        cfg.whisper_api_key = None
    get_settings.cache_clear()
    installed = get_settings()
    for field in (*RUNTIME_FIELDS, "whisper_api_key"):
        setattr(installed, field, getattr(cfg, field))
