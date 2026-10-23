"""Installation checklist backed by current settings, never by skipped-step claims."""

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.readiness import delivery_readiness
from app.config import get_settings
from app.db.models import Instance, User
from app.deps import get_db
from app.monitoring import probe_instance, states
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import admin_user
from app.security.two_factor import green_api_config, load, save, smtp_config
from app.settings_store import get_setting
from app.setup_checks import ai_provider_fingerprint, ai_provider_status, notifier_test_passed

if TYPE_CHECKING:
    from app.api.settings import TestResult

router = APIRouter(prefix="/api/setup", tags=["setup"], dependencies=[Depends(admin_user)])
DB = Annotated[AsyncSession, Depends(get_db)]
Step = Literal["openwa", "notifiers", "parents", "children", "ai", "defaults"]
KEY = "internal.setup"
OPTIONAL_STEPS = {"defaults"}


@router.get("")
async def setup_status(db: DB) -> dict[str, Any]:
    cfg = get_settings()
    progress = await load(db, KEY, {})
    phones = list(await db.scalars(select(Instance).where(Instance.enabled.is_(True))))
    roles = await get_setting(db, "phones.roles")
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    children = [i for i in phones if roles.get(str(i.id), "child") == "child" and i.id != sender_id]
    readiness = await delivery_readiness(db)
    smtp = await smtp_config(db, cfg)
    green = await green_api_config(db, cfg)
    openwa_test = await notifier_test_passed(db, "openwa")
    telegram_test = await notifier_test_passed(db, "telegram")
    notifier_tests = {
        "smtp": bool(smtp.get("verified")),
        "greenapi": bool(
            green.get("verified")
            and (green.get("delivery_verified") or await notifier_test_passed(db, "greenapi"))
        ),
        "openwa": openwa_test,
        "telegram": telegram_test,
    }
    notifier_ready = any(notifier_tests.values())
    ai = await ai_provider_status(db)
    openwa_ready = any(states.get(i.id, False) for i in phones) or (
        not phones and bool(progress.get("openwa_ready"))
    )
    parents_ready = any(r.eligible and r.user_id is not None for r in readiness.recipients)
    steps = [
        {
            "id": "openwa",
            "title": "Connect OpenWA",
            "ready": openwa_ready,
            "warning": "Messages cannot be monitored until OpenWA is reachable "
            "and a WhatsApp session is connected.",
        },
        {
            "id": "notifiers",
            "title": "Configure and test notifications",
            "ready": notifier_ready,
            "warning": "Parents may not receive alerts until at least one notification "
            "provider passes a test.",
        },
        {
            "id": "parents",
            "title": "Add a parent recipient",
            "ready": parents_ready and readiness.provider_ready,
            "warning": "Select at least one parent/admin user with an eligible destination "
            "for the active alert channel. GreenAPI and Telegram do not require individual "
            "contact approval; OpenWA and email require approval.",
        },
        {
            "id": "children",
            "title": "Connect a child phone",
            "ready": any(states.get(i.id, False) for i in children),
            "warning": "No child can be monitored until a child phone is connected to OpenWA.",
        },
        {
            "id": "ai",
            "title": "Connect and test AI providers",
            "ready": all(p["tested"] for p in ai if p["required"]),
            "warning": "Save and test the selected classification and transcription providers. "
            "Untested AI connections can leave text, photos or recordings unexamined.",
        },
        {
            "id": "defaults",
            "title": "Review important defaults",
            "ready": bool(progress.get("defaults_reviewed")),
            "warning": "Review AI providers, monitoring scope, retention, media storage "
            "and notification timing.",
        },
    ]
    for step in steps:
        step["dismissible"] = step["id"] in OPTIONAL_STEPS
    warnings = [s["warning"] for s in steps if not s["ready"]]
    # Existing fully configured installations do not interrupt Home for an optional defaults review.
    needs_setup = not progress.get("finished") and any(
        not s["ready"] for s in steps if not s["dismissible"]
    )
    return {
        "needs_setup": bool(needs_setup),
        "steps": steps,
        "warnings": warnings,
        "skipped": progress.get("skipped", []),
        "finished": bool(progress.get("finished")),
        "active_channel": readiness.channel,
        "delivery_ready": readiness.ready,
        "ai_providers": ai,
        "defaults": {
            "public_url": cfg.public_base_url,
            "monitor_direct": await get_setting(db, "scope.monitor_direct"),
            "monitor_groups": await get_setting(db, "scope.monitor_groups"),
            "monitor_from_me": await get_setting(db, "scope.monitor_from_me"),
            "media_policy": await get_setting(db, "media.policy"),
            "message_days": await get_setting(db, "retention.message_days"),
            "alert_days": await get_setting(db, "retention.alert_days"),
            "timezone": await get_setting(db, "alerts.timezone"),
            "recovery_enabled": await get_setting(db, "openwa.recovery_enabled"),
        },
        "providers": notifier_tests,
    }


@router.get("/reminders")
async def setup_reminders(db: DB, user: Annotated[User, Depends(admin_user)]) -> dict[str, Any]:
    status = await setup_status(db)
    dismissed = await load(db, f"internal.setup_reminders.{user.id}", [])
    status["steps"] = [
        step
        for step in status["steps"]
        if not step["ready"] and not (step["dismissible"] and step["id"] in dismissed)
    ]
    return status


class DismissReminder(BaseModel):
    step: Step


@router.post("/reminders/dismiss")
async def dismiss_setup_reminder(
    body: DismissReminder, db: DB, user: Annotated[User, Depends(admin_user)]
) -> dict[str, Any]:
    if body.step not in OPTIONAL_STEPS:
        raise HTTPException(
            422, "Essential setup warnings cannot be dismissed. Complete the step first."
        )
    key = f"internal.setup_reminders.{user.id}"
    dismissed = await load(db, key, [])
    await save(db, key, sorted({*dismissed, body.step}))
    await db.commit()
    return await setup_reminders(db, user)


@router.post("/check")
async def check_setup_connections(db: DB) -> dict[str, Any]:
    cfg = get_settings()
    phones = list(await db.scalars(select(Instance).where(Instance.enabled.is_(True))))
    semaphore = asyncio.Semaphore(4)

    async def probe(phone: Instance) -> None:
        async with semaphore:
            await probe_instance(phone, cfg.key_bytes)

    await asyncio.gather(*(probe(i) for i in phones))
    progress = dict(await load(db, KEY, {}))
    progress["openwa_ready"] = False
    if not phones and cfg.openwa_url and cfg.openwa_api_key:
        client = OpenWAClient(cfg.openwa_url, cfg.openwa_api_key)
        try:
            result = await client._request("GET", "/api/sessions")
            sessions = result.get("data", result) if isinstance(result, dict) else result
            if isinstance(sessions, list):
                progress["openwa_ready"] = any(
                    isinstance(s, dict) and s.get("status") == "ready" for s in sessions
                )
        except OpenWAError:
            pass
        finally:
            await client.aclose()
    progress["checked_at"] = datetime.now(UTC).isoformat()
    await save(db, KEY, progress)
    await db.commit()
    return await setup_status(db)


class SetupProgress(BaseModel):
    skip: Step | None = None
    review_defaults: bool = False
    finish: bool = False
    acknowledge_incomplete: bool = False


@router.post("/progress")
async def update_setup_progress(body: SetupProgress, db: DB) -> dict[str, Any]:
    progress = dict(await load(db, KEY, {}))
    if body.finish:
        current = await setup_status(db)
        if current["warnings"] and not body.acknowledge_incomplete:
            raise HTTPException(
                409, "Some setup steps are incomplete. Acknowledge the warnings to continue."
            )
        progress["finished"] = True
    if body.skip:
        progress["skipped"] = sorted({*progress.get("skipped", []), body.skip})
    if body.review_defaults:
        progress["defaults_reviewed"] = True
    await save(db, KEY, progress)
    await db.commit()
    return await setup_status(db)


@router.post("/ai/test/{target}")
async def test_setup_ai(
    target: Literal[
        "ollama", "ollama_image", "openai", "openai_transcription", "local_whisper", "cloudflare"
    ],
    db: DB,
) -> dict[str, Any]:
    from app.api.settings import TestResult

    started = time.monotonic()
    logger.info("setup_ai_test started target={}", target)
    fingerprint = await ai_provider_fingerprint(db, target)
    try:
        result = await asyncio.wait_for(_run_setup_ai_test(target, db), timeout=110)
    except TimeoutError:
        result = TestResult(
            ok=False, detail="Test timed out after 110 seconds. Check the provider and try again."
        )
    except Exception as exc:
        logger.warning("setup_ai_test exception target={} type={}", target, type(exc).__name__)
        result = TestResult(
            ok=False, detail="Provider test failed. Check the saved connection and server logs."
        )
    logger.info(
        "setup_ai_test completed target={} ok={} seconds={:.1f}",
        target,
        result.ok,
        time.monotonic() - started,
    )
    await save(
        db,
        f"internal.ai_test.{target}",
        {
            "ok": result.ok,
            "fingerprint": fingerprint,
            "detail": result.detail,
            "checked_at": datetime.now(UTC).isoformat(),
        },
    )
    await db.commit()
    return result.model_dump()


async def _run_setup_ai_test(target: Any, db: AsyncSession) -> "TestResult":
    from app.api.settings import SILENCE, TestRequest, TestResult, test_provider
    from app.jobs.queue import PermanentError, TransientError
    from app.settings_store import get_secret
    from app.transcription.openai import OpenAITranscriber

    cfg = get_settings()
    if target == "openai_transcription":
        key = await get_secret(db, "openai.api_key", cfg.key_bytes)
        result = TestResult(ok=False, detail="Save an OpenAI API key first")
        if key:
            client = OpenAITranscriber(key, await get_setting(db, "transcription.openai_model"))
            try:
                await client.transcribe(SILENCE, "audio/wav")
                result = TestResult(ok=True, detail="OpenAI transcribed the built-in test clip")
            except (PermanentError, TransientError):
                result = TestResult(ok=False, detail="OpenAI transcription test failed")
            finally:
                await client.aclose()
    else:
        body = TestRequest()
        if target in ("ollama", "ollama_image"):
            body.base_url, body.model = cfg.ollama_base_url, cfg.ollama_model
        elif target == "local_whisper":
            body.model = None if cfg.whisper_model == "auto" else cfg.whisper_model
        result = await test_provider(target, db, cfg, body)
    return result
