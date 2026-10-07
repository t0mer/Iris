"""/api/settings: flat key map; secrets are write-only."""

import time
from collections import deque
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import ALERT_PREFIX
from app.alerts.delivery import recipient_chat_id
from app.alerts.format import with_signed_link
from app.classify.moderation import ModerationClient
from app.classify.thresholds import DEFAULT_THRESHOLDS, effective_thresholds
from app.config import Settings, get_settings
from app.db.models import Instance
from app.deps import get_db
from app.jobs.queue import PermanentError, TransientError
from app.media.factory import MediaOverrides, build_store
from app.media.store import MediaStoreError
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import current_user
from app.security.crypto import decrypt
from app.settings_store import REGISTRY, all_settings, get_secret, get_setting, set_setting
from app.transcription.cloudflare import CloudflareTranscriber

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(current_user)])


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


@router.get("")
async def read_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    return await all_settings(db)


class ThresholdRow(BaseModel):
    category: str
    low: float
    high: float
    default_low: float
    default_high: float


@router.get("/thresholds")
async def thresholds(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ThresholdRow]:
    """Effective per-category thresholds next to their defaults, for the settings table."""
    effective = effective_thresholds(await get_setting(db, "classification.thresholds"))
    return [
        ThresholdRow(
            category=cat,
            low=low,
            high=high,
            default_low=DEFAULT_THRESHOLDS[cat][0],
            default_high=DEFAULT_THRESHOLDS[cat][1],
        )
        for cat, (low, high) in sorted(effective.items())
    ]


@router.put("")
async def update_settings(
    body: SettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    cfg: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    # Validate everything first so a bad key never leaves a half-applied update.
    errors: dict[str, str] = {}
    for key, value in body.settings.items():
        spec = REGISTRY.get(key)
        if spec is None:
            errors[key] = "unknown setting"
            continue
        try:
            spec.validate(value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    for key, value in body.settings.items():
        await set_setting(db, key, value, cfg.key_bytes)
    return await all_settings(db)


SILENCE = Path(__file__).resolve().parent.parent / "assets" / "silence.wav"


class TestRequest(BaseModel):
    """Values entered in the form but not saved yet; blank fields fall back to the saved ones."""

    api_key: str | None = None
    sender_instance_id: int | None = None
    recipient: str | None = None
    account_id: str | None = None
    api_token: str | None = None
    model: str | None = None
    media: "MediaTest | None" = None


class MediaTest(BaseModel):
    backend: Literal["local", "s3"] | None = None
    endpoint: str | None = Field(default=None, max_length=300)
    bucket: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    access_key: str | None = Field(default=None, max_length=200)
    secret_key: str | None = Field(default=None, max_length=300)
    prefix: str | None = Field(default=None, max_length=200)
    path_style: bool | None = None


class TestResult(BaseModel):
    ok: bool
    detail: str


@router.post("/test/{target}")
async def test_provider(
    target: Literal["openai", "cloudflare", "alert", "media"],
    db: Annotated[AsyncSession, Depends(get_db)],
    cfg: Annotated[Settings, Depends(get_settings)],
    body: TestRequest | None = None,
) -> TestResult:
    body = body or TestRequest()
    try:
        if target == "openai":
            key = body.api_key or await get_secret(db, "openai.api_key", cfg.key_bytes)
            if not key:
                return TestResult(ok=False, detail="No OpenAI API key set")
            client = ModerationClient(key)
            try:
                model = str(await get_setting(db, "classification.model"))
                await client.moderate(model, "Hello, this is a connection test.")
            finally:
                await client.aclose()
            return TestResult(ok=True, detail="OpenAI Moderation answered")
        if target == "cloudflare":
            account = body.account_id or await get_setting(
                db, "transcription.cloudflare_account_id"
            )
            token = body.api_token or await get_secret(
                db, "transcription.cloudflare_api_token", cfg.key_bytes
            )
            model = body.model or str(await get_setting(db, "transcription.cloudflare_model"))
            if not account or not token:
                return TestResult(
                    ok=False, detail="Cloudflare account ID and API token are required"
                )
            try:
                cf = CloudflareTranscriber(account, token, model)
            except ValueError as exc:
                return TestResult(ok=False, detail=str(exc))
            try:
                await cf.transcribe(SILENCE, "audio/wav")  # a bundled 1-second silent clip
            finally:
                await cf.aclose()
            return TestResult(ok=True, detail="Cloudflare Workers AI transcribed the test clip")
        if target == "media":
            return await _test_media(db, cfg, body)
        return await _test_alert(db, cfg, body)
    except (PermanentError, TransientError) as exc:
        return TestResult(ok=False, detail=str(exc))  # messages are static, never secrets


_media_tests: deque[float] = deque()
MEDIA_TESTS_PER_WINDOW, MEDIA_WINDOW_SECONDS = 10, 300


async def _test_media(db: AsyncSession, cfg: Settings, body: TestRequest) -> TestResult:
    """Write, read back and delete a tiny object in the entered (or saved) storage."""
    now = time.monotonic()
    while _media_tests and now - _media_tests[0] > MEDIA_WINDOW_SECONDS:
        _media_tests.popleft()
    if len(_media_tests) >= MEDIA_TESTS_PER_WINDOW:
        return TestResult(ok=False, detail="Too many tests. Wait a few minutes and try again.")
    _media_tests.append(now)
    typed = body.media or MediaTest()
    try:
        store = await build_store(
            db, cfg.key_bytes, cfg.data_dir, MediaOverrides(**typed.model_dump())
        )
        try:
            await store.probe()
        finally:
            await store.aclose()
    except MediaStoreError as exc:
        return TestResult(ok=False, detail=str(exc))  # messages are static, never secrets
    return TestResult(ok=True, detail="Storage works: a test file was written, read and deleted.")


async def _test_alert(db: AsyncSession, cfg: Settings, body: TestRequest) -> TestResult:
    """Send a real WhatsApp test message with the entered (or saved) sender and recipient."""
    sender_id = body.sender_instance_id or await get_setting(db, "alerts.sender_instance_id")
    recipient = body.recipient or await get_setting(db, "alerts.recipient")
    sender = await db.get(Instance, sender_id) if sender_id else None
    if sender is None or not sender.openwa_api_key_enc:
        return TestResult(
            ok=False, detail="Choose an alert sender instance that has an OpenWA API key"
        )
    if not recipient:
        return TestResult(ok=False, detail="Enter the alert recipient (phone number or chat ID)")
    client = OpenWAClient(sender.openwa_base_url, decrypt(cfg.key_bytes, sender.openwa_api_key_enc))
    try:
        await client.send_text(
            sender.openwa_instance_id,
            recipient_chat_id(recipient),
            # Signed like a real alert (the signature covers this exact text), so Iris skips it
            # if it comes back through a monitored session rather than classifying it.
            with_signed_link(
                f"{ALERT_PREFIX} (test)\nAlert delivery is working.",
                cfg.public_base_url,
                cfg.key_bytes,
                0,
            ),
        )
    except OpenWAError as exc:
        hint = " (is the OpenWA session running?)" if exc.status == 400 else ""
        return TestResult(ok=False, detail=f"OpenWA: {exc.message}{hint}")
    finally:
        await client.aclose()
    return TestResult(ok=True, detail="Test message sent")
