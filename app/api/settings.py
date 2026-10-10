"""/api/settings: flat key map; secrets are write-only."""

import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts import ALERT_PREFIX
from app.alerts.format import with_signed_link
from app.alerts.pacing import reserve
from app.alerts.readiness import bind_recipient_users, delivery_readiness
from app.alerts.recipients import recipients
from app.classify.moderation import ModerationClient
from app.classify.ollama import OllamaModerator
from app.classify.thresholds import DEFAULT_THRESHOLDS, effective_thresholds
from app.config import Settings, get_settings
from app.db.models import Instance, User
from app.deps import get_db
from app.jobs.queue import DeferredError, PermanentError, TransientError, enqueue
from app.media.factory import MediaOverrides, build_store
from app.media.store import MediaStoreError
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import admin_user
from app.security.crypto import decrypt
from app.settings_store import (
    REGISTRY,
    RUNTIME_FIELDS,
    all_settings,
    get_secret,
    get_setting,
    reload_runtime_settings,
    set_setting,
)
from app.transcription.cloudflare import CloudflareTranscriber

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(admin_user)])


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


@router.get("/alert-readiness")
async def alert_readiness(
    db: Annotated[AsyncSession, Depends(get_db)],
    channel: Literal["openwa", "telegram", "smtp", "greenapi"] | None = None,
) -> dict[str, Any]:
    return (await delivery_readiness(db, channel)).public()


@router.post("/alert-readiness")
async def preview_alert_readiness(
    body: SettingsUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    clean = {}
    for key, value in body.settings.items():
        if key not in REGISTRY or not key.startswith("alerts."):
            raise HTTPException(422, "Only alert settings can be previewed")
        try:
            clean[key] = REGISTRY[key].validate(value)
        except ValueError as exc:
            raise HTTPException(422, {key: str(exc)}) from None
    return (await delivery_readiness(db, overrides=clean)).public()


@router.get("")
async def read_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    values = await all_settings(db)
    cfg = get_settings()
    values["provider_media"] = {
        "archive_enabled": cfg.openwa_archive_enabled,
        "archive_outbound": cfg.openwa_archive_outbound,
        "archive_ttl_days": cfg.openwa_archive_ttl_days,
        "download_timeout_seconds": cfg.openwa_media_timeout_seconds,
        "managed_by": "OpenWA deployment",
    }
    for field in RUNTIME_FIELDS:
        values["runtime." + field] = getattr(cfg, field)
    values["runtime.transcription_provider"] = cfg.transcription_provider or (
        "local_whisper" if cfg.whisper_url else await get_setting(db, "transcription.provider")
    )
    values["runtime.whisper_api_key"] = {"set": bool(cfg.whisper_api_key)}
    if cfg.classification_provider == "ollama" or cfg.whisper_url:
        # Operational metadata only; secrets stay write-only and cloud settings stay intact.
        values["local_providers"] = {
            "classification": cfg.classification_provider,
            "ollama_model": cfg.ollama_model,
            "transcription": values["runtime.transcription_provider"],
            "transcription_model": cfg.whisper_model,
            "api_key_set": bool(cfg.whisper_api_key),
        }
    return values


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
    request: Request,
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
    if "alerts.recipient_children" in body.settings and "alerts.recipient_children" not in errors:
        roles = await get_setting(db, "phones.roles")
        sender_id = body.settings.get(
            "alerts.sender_instance_id", await get_setting(db, "alerts.sender_instance_id")
        )
        child_ids = {
            child.id
            for child in await db.scalars(select(Instance))
            if roles.get(str(child.id), "child") == "child" and child.id != sender_id
        }
        assigned = {
            child for ids in body.settings["alerts.recipient_children"].values() for child in ids
        }
        if not assigned.issubset(child_ids):
            errors["alerts.recipient_children"] = "Select existing child phones"
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    if body.settings.get("alerts.sender_instance_id"):
        sender = await db.get(Instance, body.settings["alerts.sender_instance_id"])
        if (
            sender
            and sender.phone_number
            and await db.scalar(
                select(User.id).where(User.whatsapp_number == "+" + sender.phone_number.lstrip("+"))
            )
        ):
            raise HTTPException(
                422, "OpenWA alert sender must differ from users' personal WhatsApp numbers."
            )
    if "alerts.channel" in body.settings:
        # Recheck even when returning to a previously saved channel. Approval
        # belongs to the current contact, never to a prior channel selection.
        clean = {key: REGISTRY[key].validate(value) for key, value in body.settings.items()}
        readiness = await delivery_readiness(db, overrides=clean)
        if not readiness.ready:
            raise HTTPException(422, {"alerts.channel": readiness.error})
    # Changing a host must not send a saved credential to that new host unnoticed.
    if body.settings.get("runtime.whisper_url") and cfg.whisper_api_key:
        from urllib.parse import urlsplit

        entered = urlsplit(str(body.settings["runtime.whisper_url"]))
        old = urlsplit(cfg.whisper_url or "")
        if (
            entered.netloc != old.netloc
            and not body.settings.get("runtime.whisper_api_key")
            and body.settings.get("runtime.whisper_use_environment_key") is not False
        ):
            raise HTTPException(
                status_code=422, detail="Re-enter the transcription API key when changing its host"
            )
    if body.settings.get("alerts.alert_on_review") is True and not await get_setting(
        db, "alerts.alert_on_review"
    ):
        # Enabling notifications must not broadcast the historical review backlog.
        await set_setting(
            db, "alerts.review_notify_since", datetime.now(UTC).isoformat(), cfg.key_bytes
        )
    for key, value in body.settings.items():
        await set_setting(db, key, value, cfg.key_bytes)
    if any(key.startswith("alerts.") for key in body.settings):
        await bind_recipient_users(db)
        await db.commit()
    if any(key.startswith("runtime.") for key in body.settings):
        await reload_runtime_settings(db)
        updated = get_settings()
        await request.app.state.workers.reconfigure(updated.workers, updated.delivery_workers)
    return await read_settings(db)


SILENCE = Path(__file__).resolve().parent.parent / "assets" / "silence.wav"


class TestRequest(BaseModel):
    """Values entered in the form but not saved yet; blank fields fall back to the saved ones."""

    api_key: str | None = None
    sender_instance_id: int | None = None
    recipient: str | None = None
    account_id: str | None = None
    api_token: str | None = None
    model: str | None = None
    base_url: str | None = None
    endpoint: str | None = None
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


@router.post("/ollama/models")
async def ollama_models(
    body: TestRequest, cfg: Annotated[Settings, Depends(get_settings)]
) -> dict[str, Any]:
    import asyncio

    url = REGISTRY["runtime.ollama_base_url"].validate(body.base_url or cfg.ollama_base_url)
    try:
        async with httpx.AsyncClient(
            base_url=url.rstrip("/"), timeout=3, trust_env=False
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            rows = response.json()["models"]
            if not isinstance(rows, list):
                raise ValueError("Invalid model list")
            names = sorted(
                {r["name"] for r in rows if isinstance(r, dict) and isinstance(r.get("name"), str)}
            )
            items = [{"name": name, "vision": None} for name in names]
            slots = asyncio.Semaphore(4)

            async def capabilities(item: dict[str, Any]) -> None:
                async with slots:
                    try:
                        metadata = await client.post("/api/show", json={"model": item["name"]})
                        metadata.raise_for_status()
                        caps = metadata.json().get("capabilities")
                        if isinstance(caps, list):
                            item["vision"] = "vision" in caps
                    except (httpx.HTTPError, ValueError, AttributeError):
                        pass  # Keep the installed model visible with unknown capabilities.

            await asyncio.gather(*(capabilities(item) for item in items[:20]))
            return {"models": items}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(
            502, "Could not detect installed Ollama models. Check the endpoint and try again."
        ) from exc


@router.post("/test/{target}")
async def test_provider(
    target: Literal[
        "openai",
        "cloudflare",
        "alert",
        "media",
        "ollama",
        "ollama_image",
        "ollama_embedding",
        "local_whisper",
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    cfg: Annotated[Settings, Depends(get_settings)],
    body: TestRequest | None = None,
) -> TestResult:
    body = body or TestRequest()
    try:
        if target in ("ollama", "ollama_image", "ollama_embedding"):
            if cfg.classification_provider != "ollama" and not body.base_url:
                return TestResult(ok=False, detail="Ollama is not enabled")
            url = REGISTRY["runtime.ollama_base_url"].validate(body.base_url or cfg.ollama_base_url)
            model = body.model or cfg.ollama_model
            if target == "ollama_embedding":
                model = body.model or await get_setting(
                    db, "classification.learning_embedding_model"
                )
                if not model:
                    return TestResult(ok=False, detail="Enter an installed embedding model name")
            local = OllamaModerator(url, model)
            try:
                if target == "ollama_embedding":
                    vectors = await local.embed(model, ["שלום, זו בדיקה", "Hello, this is a test"])
                    return TestResult(
                        ok=True,
                        detail=f"Embedding model answered: {len(vectors[0])} dimensions",
                    )
                if target == "ollama_image":
                    import base64

                    sample = SILENCE.parent / "vision-test.png"
                    encoded = base64.b64encode(sample.read_bytes()).decode()
                    await local.moderate(
                        model,
                        [
                            {
                                "type": "text",
                                "text": "Classify this sample image and its visible contents.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64," + encoded},
                            },
                        ],
                    )
                else:
                    await local.moderate(model, "Hello, this is a connection test.")
            finally:
                await local.aclose()
            return TestResult(
                ok=True,
                detail=(
                    "Ollama vision inference passed on a built-in sample image. "
                    "Valid category scores returned; this is not an accuracy benchmark."
                    if target == "ollama_image"
                    else "Ollama answered with valid moderation output"
                ),
            )
        if target == "local_whisper":
            endpoint = REGISTRY["runtime.whisper_url"].validate(body.endpoint or cfg.whisper_url)
            if not endpoint:
                return TestResult(ok=False, detail="Local transcription is not enabled")
            # Check authenticated capabilities, rather than submitting silence as real speech.
            from urllib.parse import urlsplit, urlunsplit

            parts = urlsplit(endpoint)
            if (
                parts.netloc != urlsplit(cfg.whisper_url or "").netloc
                and cfg.whisper_api_key
                and not body.api_key
            ):
                return TestResult(ok=False, detail="Re-enter the API key when testing a new host")
            url = urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))
            token = body.api_key or cfg.whisper_api_key
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with httpx.AsyncClient(timeout=10, trust_env=False) as http_client:
                response = await http_client.get(url, headers=headers)
            if response.status_code != 200:
                return TestResult(
                    ok=False, detail="Local transcription authentication or connection failed"
                )
            models = response.json().get("data")
            if not isinstance(models, list):
                return TestResult(
                    ok=False, detail="Local transcription returned invalid capabilities"
                )
            if body.model and body.model not in [
                m.get("id") for m in models if isinstance(m, dict)
            ]:
                return TestResult(ok=False, detail="Selected transcription model is not available")
            return TestResult(
                ok=True,
                detail=(
                    "Local transcription authenticated; models available. "
                    "Run a real audio test to verify inference."
                ),
            )
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
    except (httpx.HTTPError, ValueError, AttributeError):
        return TestResult(ok=False, detail="Local provider unreachable or returned invalid output")


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
    channel = str(await get_setting(db, "alerts.channel"))
    if channel != "openwa":
        readiness = await delivery_readiness(db, channel)
        if not readiness.ready:
            return TestResult(ok=False, detail=readiness.error)
        targets = recipients(await get_setting(db, "alerts.recipient"))
        text = with_signed_link(
            f"{ALERT_PREFIX} (test)\nAlert delivery is working.",
            cfg.public_base_url,
            cfg.key_bytes,
            0,
        )
        await enqueue(db, "test_alert", {"channel": channel, "recipients": targets, "text": text})
        await db.commit()
        return TestResult(
            ok=True,
            detail="Test notification queued. Check Jobs for delivery status.",
        )
    sender_id = body.sender_instance_id or await get_setting(db, "alerts.sender_instance_id")
    recipient = body.recipient or await get_setting(db, "alerts.recipient")
    sender = await db.get(Instance, sender_id) if sender_id else None
    if sender is None or not sender.openwa_api_key_enc:
        return TestResult(
            ok=False, detail="Choose an alert sender instance that has an OpenWA API key"
        )
    if not recipient:
        return TestResult(ok=False, detail="Enter the alert recipient (phone number or chat ID)")
    try:
        targets = recipients(recipient)
    except ValueError as exc:
        return TestResult(ok=False, detail=str(exc))
    if not targets:
        return TestResult(ok=False, detail="Enter at least one parent recipient")
    readiness = await delivery_readiness(
        db, channel, {"alerts.recipient": recipient, "alerts.sender_instance_id": sender_id}
    )
    if not readiness.ready or any(not r.eligible for r in readiness.recipients):
        return TestResult(
            ok=False,
            detail=readiness.error
            or " ".join(f"{r.name}: {r.reason}" for r in readiness.recipients if not r.eligible),
        )
    destinations = {r.target: r.destination for r in readiness.recipients if r.destination}
    client = OpenWAClient(sender.openwa_base_url, decrypt(cfg.key_bytes, sender.openwa_api_key_enc))
    errors: list[str] = []
    completed: list[str] = []
    test_text = with_signed_link(
        f"{ALERT_PREFIX} (test)\nAlert delivery is working.", cfg.public_base_url, cfg.key_bytes, 0
    )
    try:
        for target in targets:
            try:
                await reserve(db, f"openwa:{sender.id}", target)
            except DeferredError as exc:
                if completed:
                    await enqueue(
                        db,
                        "test_alert",
                        {
                            "sender_id": sender_id,
                            "recipients": targets,
                            "delivered_recipients": completed,
                            "text": test_text,
                        },
                        max_attempts=3,
                    )
                    return TestResult(
                        ok=True,
                        detail=(
                            "Test sent to the first parent; remaining test messages queued. "
                            "Check Jobs for delivery status."
                        ),
                    )
                return TestResult(
                    ok=False,
                    detail=(
                        f"Sending limit reached. Retry in {int(exc.delay) + 1} seconds. "
                        "Earlier recipients may already have received the test."
                    ),
                )
            try:
                await client.send_text(
                    sender.openwa_instance_id,
                    destinations[target],
                    test_text,
                )
                completed.append(target)
            except OpenWAError as exc:
                hint = " (is the OpenWA session running?)" if exc.status == 400 else ""
                errors.append(f"OpenWA: {exc.message}{hint}")
    finally:
        await client.aclose()
    if errors:
        return TestResult(
            ok=False, detail=f"{len(errors)} recipient(s) failed: " + "; ".join(errors)
        )
    from app.setup_checks import record_notifier_test

    # Entered test values must match the saved deployment to count toward setup.
    if sender_id == await get_setting(db, "alerts.sender_instance_id") and targets == recipients(
        await get_setting(db, "alerts.recipient")
    ):
        await record_notifier_test(db, "openwa")
    await db.commit()
    return TestResult(
        ok=True,
        detail="Test message sent"
        if len(targets) == 1
        else f"Test message sent to {len(targets)} parents",
    )
