"""Read-only provider probes and durable, hourly operational notices."""

import asyncio
import smtplib
import ssl
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.channels import build_client
from app.alerts.pacing import reserve
from app.alerts.readiness import delivery_readiness
from app.config import get_settings
from app.db.models import Instance, Job, Setting
from app.jobs.queue import ClaimedJob, DeferredError, enqueue
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.security.two_factor import green_api_config, smtp_config
from app.settings_store import get_secret, get_setting

if TYPE_CHECKING:
    from app.jobs.handlers import Deps

PREFIX = "internal.provider_health."
_delivery_lock = asyncio.Lock()


async def health_rows(db: AsyncSession) -> list[dict[str, Any]]:
    return [
        dict(row.value, provider=row.key.removeprefix(PREFIX))
        for row in await db.scalars(
            select(Setting).where(Setting.key.startswith(PREFIX)).order_by(Setting.key)
        )
    ]


def _smtp_probe(config: dict[str, Any]) -> None:
    context = ssl.create_default_context()
    klass = smtplib.SMTP_SSL if config.get("tls") == "ssl" else smtplib.SMTP
    options: dict[str, Any] = {"timeout": 8}
    if config.get("tls") == "ssl":
        options["context"] = context
    with klass(config["host"], int(config.get("port", 587)), **options) as client:
        client.ehlo()
        if config.get("tls") != "ssl":
            client.starttls(context=context)
            client.ehlo()
        if config.get("username"):
            client.login(config["username"], config.get("password", ""))


async def probe_providers(db: AsyncSession) -> dict[str, tuple[str, bool, str | None]]:
    cfg = get_settings()
    probes: dict[str, tuple[str, Any]] = {}

    async def web(
        url: str, headers: dict[str, str] | None = None, expected: tuple[str, Any] | None = None
    ) -> None:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            if expected and response.json().get(expected[0]) != expected[1]:
                raise ValueError("Provider is not ready")

    instances = list(await db.scalars(select(Instance)))
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    openwa = sorted(
        [i for i in instances if i.enabled or i.id == sender_id], key=lambda i: i.id != sender_id
    )
    if openwa or (cfg.openwa_url and cfg.openwa_api_key):

        async def check_openwa() -> None:
            seen = set()
            for instance in openwa:
                if not instance.openwa_api_key_enc:
                    raise ValueError("OpenWA API key is not set")
                if instance.openwa_base_url not in seen:
                    seen.add(instance.openwa_base_url)
                    client = OpenWAClient(
                        instance.openwa_base_url,
                        decrypt(cfg.key_bytes, instance.openwa_api_key_enc),
                    )
                    try:
                        await client._request("GET", "/api/health/ready")
                        if instance.id == sender_id and not await client.session_ready(
                            instance.openwa_instance_id
                        ):
                            raise ValueError("Alert sender is not connected")
                    finally:
                        await client.aclose()
            if not openwa:
                client = OpenWAClient(cfg.openwa_url or "", cfg.openwa_api_key or "")
                try:
                    await client._request("GET", "/api/health/ready")
                finally:
                    await client.aclose()

        probes["openwa"] = ("OpenWA", check_openwa())
    green = await green_api_config(db, cfg)
    if green.get("instance_id") and green.get("token"):
        url = (
            f"{green['api_url']}/waInstance{green['instance_id']}/getStateInstance/{green['token']}"
        )
        probes["greenapi"] = ("GreenAPI", web(url, expected=("stateInstance", "authorized")))
    telegram = await get_secret(db, "alerts.telegram_bot_token", cfg.key_bytes)
    if telegram:
        probes["telegram"] = (
            "Telegram",
            web(f"https://api.telegram.org/bot{telegram}/getMe", expected=("ok", True)),
        )
    smtp = await smtp_config(db, cfg)
    if smtp.get("host"):
        probes["smtp"] = ("SMTP", asyncio.to_thread(_smtp_probe, smtp))
    if cfg.classification_provider == "ollama":
        probes["ollama"] = ("Ollama", web(cfg.ollama_base_url.rstrip("/") + "/api/tags"))
    if cfg.whisper_url:
        headers = (
            {"Authorization": "Bearer " + cfg.whisper_api_key} if cfg.whisper_api_key else None
        )
        parts = urlsplit(cfg.whisper_url)
        models_url = urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))

        async def check_whisper() -> None:
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                response = await client.get(models_url, headers=headers)
                response.raise_for_status()
                if not isinstance(response.json().get("data"), list):
                    raise ValueError("Invalid transcription capabilities")

        probes["whisper"] = ("Whisper", check_whisper())
    openai_key = await get_secret(db, "openai.api_key", cfg.key_bytes)
    transcription = cfg.transcription_provider or await get_setting(db, "transcription.provider")
    if openai_key and (cfg.classification_provider == "openai" or transcription == "openai"):
        probes["openai"] = (
            "OpenAI",
            web("https://api.openai.com/v1/models", {"Authorization": "Bearer " + openai_key}),
        )
    if transcription == "cloudflare":
        account = await get_setting(db, "transcription.cloudflare_account_id")
        token = await get_secret(db, "transcription.cloudflare_api_token", cfg.key_bytes)
        if account and token:
            probes["cloudflare"] = (
                "Cloudflare",
                web(
                    f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/models/search",
                    {"Authorization": "Bearer " + token},
                    ("success", True),
                ),
            )

    async def check(name: str, label: str, probe: Any) -> tuple[str, str, bool, str | None]:
        try:
            await asyncio.wait_for(probe, timeout=12)
            return name, label, True, None
        except Exception as exc:
            # Provider URLs can contain tokens. Keep only safe exception types/status codes.
            error = (
                f"HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            if isinstance(exc, OpenWAError):
                error = f"HTTP {exc.status}" if exc.status else type(exc.__cause__).__name__
            if isinstance(exc, ValueError) and str(exc) in {
                "Provider is not ready",
                "Alert sender is not connected",
                "OpenWA API key is not set",
            }:
                error = str(exc)
            return name, label, False, error

    results = await asyncio.gather(
        *(check(name, label, probe) for name, (label, probe) in probes.items())
    )
    return {name: (label, ready, error) for name, label, ready, error in results}


async def record_health(
    db: AsyncSession, results: dict[str, tuple[str, bool, str | None]], now: datetime
) -> None:
    interval = max(60, int(await get_setting(db, "alerts.provider_notification_minutes"))) * 60
    for name, (label, ready, error) in results.items():
        row = await db.get(Setting, PREFIX + name)
        previous = dict(row.value) if row else {}
        status = "up" if ready else "down"
        value = dict(previous, name=label, status=status, error=error, checked_at=now.isoformat())
        if previous.get("status") != status:
            value["changed_at"] = now.isoformat()
            value["delivery_error"] = None
        if row is None:
            row = Setting(key=PREFIX + name, value=value)
            db.add(row)
        else:
            row.value = value
        due = now.timestamp() - float(previous.get("queued_at", 0)) >= interval
        needs_notice = not ready or previous.get("notice_status") == "down"
        if due and needs_notice:
            value["queued_at"] = now.timestamp()
            value["notice_status"] = status
            row.value = dict(value)
            await enqueue(
                db,
                "provider_notice",
                {"provider": name, "status": status, "observed_at": now.isoformat()},
                max_attempts=1,
            )
    # Removed/unconfigured providers must not remain listed as down.
    for row in list(await db.scalars(select(Setting).where(Setting.key.startswith(PREFIX)))):
        if row.key.removeprefix(PREFIX) not in results:
            await db.delete(row)
    await db.commit()


async def monitor(deps: "Deps") -> dict[str, int]:
    async with deps.session_factory() as db:
        results = await probe_providers(db)
        await record_health(db, results, datetime.now(UTC))
        return {"checked": len(results), "down": sum(not ready for _, ready, _ in results.values())}


async def deliver_notice(job: ClaimedJob, deps: "Deps") -> None:
    async with _delivery_lock, deps.session_factory() as db:
        row = await db.get(Setting, PREFIX + str(job.payload["provider"]))
        if row is None:
            return
        value = dict(row.value)
        if value["status"] != job.payload["status"]:
            return  # An old outage must not be announced after recovery.
        now = datetime.now(UTC).timestamp()
        interval = max(60, int(await get_setting(db, "alerts.provider_notification_minutes"))) * 60
        if job.payload.get("attempt_reserved") is not True:
            if now - float(value.get("attempted_at", 0)) < interval:
                return
            value["attempted_at"] = now
            value["queued_at"] = now
            row.value = value
            job.payload["attempt_reserved"] = True
            stored = await db.get(Job, job.id)
            if stored:
                stored.payload = dict(job.payload)
            await db.commit()
        channel = str(await get_setting(db, "alerts.provider_notification_channel"))
        default_channel = str(await get_setting(db, "alerts.channel"))
        overrides = {
            "alerts.recipient": await get_setting(db, "alerts.system_recipient"),
            "alerts.recipient_contacts": await get_setting(db, "alerts.system_contacts"),
            "alerts.recipient_children": {},
            "alerts.recipient_channels": {},
        }
        readiness = await delivery_readiness(
            db, default_channel if channel == "mixed" else channel, overrides
        )
        sender_id = await get_setting(db, "alerts.sender_instance_id")
        sender = await db.get(Instance, sender_id) if sender_id else None
        down = {r["provider"] for r in await health_rows(db) if r["status"] == "down"}
        done = list(job.payload.get("delivered_recipients", []))
        attempted = list(job.payload.get("attempted_recipients", []))
        errors = []
        for recipient in readiness.recipients:
            transport = default_channel if channel == "mixed" else channel
            if not recipient.eligible or transport in down or recipient.target in attempted:
                continue
            client = await build_client(db, sender, deps.key_bytes, transport, overrides)
            try:
                await reserve(db, client.sender_key, recipient.target)
                # Reserve before sending: an uncertain response or recovered worker must
                # never resend the same operational notice within its hourly allowance.
                attempted.append(recipient.target)
                job.payload["attempted_recipients"] = list(attempted)
                stored = await db.get(Job, job.id)
                if stored:
                    stored.payload = dict(job.payload)
                await db.commit()
                text = (
                    f"Iris: {value['name']} "
                    f"{'is unavailable' if value['status'] == 'down' else 'is available again'}.\n"
                    "Open Providers to check the connection."
                )
                await client.send_text("", recipient.target, text)
                done.append(recipient.target)
                job.payload["delivered_recipients"] = done
                stored = await db.get(Job, job.id)
                if stored:
                    stored.payload = dict(job.payload)
                await db.commit()
            except DeferredError:
                await db.refresh(row)
                row.value = dict(
                    row.value, delivered_count=len(done), delivery_error="DeferredError"
                )
                await db.commit()
                raise  # Keep the unsent recipient queued until pacing permits delivery.
            except Exception as exc:
                errors.append(type(exc).__name__)
            finally:
                await client.aclose()
        await db.refresh(row)
        row.value = dict(
            row.value,
            delivered_count=len(done),
            delivery_error="No system alert recipients selected."
            if not readiness.recipients
            else ", ".join(errors)
            if errors
            else (
                None
                if done
                else row.value.get("delivery_error") or "No healthy eligible alert channel"
            ),
        )
        await db.commit()
