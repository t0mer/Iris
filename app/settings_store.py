"""Runtime settings in the `settings` table: a typed registry with defaults and validation.

Secrets are AES-256-GCM encrypted at rest and never returned by the API (only `{"set": bool}`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.thresholds import validate_thresholds
from app.db.models import Setting
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


REGISTRY: dict[str, Spec] = {
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
    "classification.thresholds": Spec({}, _thresholds),
    "classification.context_window_size": Spec(8, _int_range(1, 20)),
    "classification.context_max_age_hours": Spec(6, _int_range(1, 168)),
    "scope.monitor_from_me": Spec(True, _bool),
    "scope.monitor_direct": Spec(True, _bool),
    "scope.monitor_groups": Spec(True, _bool),
    "retention.message_days": Spec(90, _int_range(1, 3650)),
    "retention.alert_days": Spec(365, _int_range(1, 3650)),
    "alerts.sender_instance_id": Spec(None, _opt_int),
    "alerts.recipient": Spec(None, _opt_str),
    "alerts.cooldown_minutes": Spec(10, _int_range(0, 1440)),
    "alerts.alert_on_review": Spec(False, _bool),
    "alerts.notify_changes": Spec(True, _bool),
    "alerts.timezone": Spec("Asia/Jerusalem", _timezone),
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
