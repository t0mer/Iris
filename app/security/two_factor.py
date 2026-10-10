"""Encrypted SMTP configuration and delivery of single-use verification codes."""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Setting, User
from app.security.crypto import decrypt

CONFIG_KEY = "security.smtp"
ENABLED_KEY = "security.two_factor"
GREEN_API_KEY = "security.green_api"


class _GreenAPILogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if "/waInstance" in record.getMessage():
            record.msg = "GreenAPI HTTP request (credential URL redacted)"
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_GreenAPILogFilter())


async def load(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(Setting, key)
    return row.value if row else default


async def save(db: AsyncSession, key: str, value: Any, secret: bool = False) -> None:
    row = await db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value, is_secret=secret)
        db.add(row)
    else:
        row.value = value
    await db.flush()


def digest(cfg: Settings, challenge: str, code: str) -> str:
    return hmac.new(cfg.key_bytes, f"otp:{challenge}:{code}".encode(), hashlib.sha256).hexdigest()


def email_address(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
        raise ValueError("Enter a valid email address")
    return value


def whatsapp_number(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise ValueError(
            "Enter a personal WhatsApp number with + and country code, e.g. +972501234567"
        )
    return value


async def smtp_config(db: AsyncSession, cfg: Settings) -> dict[str, Any]:
    encrypted = await load(db, CONFIG_KEY)
    return json.loads(decrypt(cfg.key_bytes, encrypted)) if encrypted else {}


async def green_api_config(db: AsyncSession, cfg: Settings) -> dict[str, Any]:
    encrypted = await load(db, GREEN_API_KEY)
    return json.loads(decrypt(cfg.key_bytes, encrypted)) if encrypted else {}


async def green_sender_number(config: dict[str, Any], *, refresh: bool = False) -> str | None:
    """Identify the sending account without sending a message or reading chats."""
    if config.get("sender_number") and not refresh:
        return str(config["sender_number"])
    if not config.get("instance_id") or not config.get("token"):
        return None
    url = f"{config['api_url']}/waInstance{config['instance_id']}/getSettings/{config['token']}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            wid = response.json().get("wid", "")
        number = whatsapp_number("+" + str(wid).split("@")[0].lstrip("+"))
        if not number:
            raise ValueError("Missing account identity")
    except (httpx.HTTPError, ValueError, AttributeError):
        raise HTTPException(
            503,
            "Could not verify the GreenAPI sender number. Check its connection in Notifications.",
        ) from None
    config["sender_number"] = number
    return number


async def whatsapp_ready(db: AsyncSession, cfg: Settings) -> bool:
    return bool((await green_api_config(db, cfg)).get("verified"))


async def available_channels(db: AsyncSession, cfg: Settings, user: User) -> list[str]:
    channels = []
    if user.email and user.email_verified and (await smtp_config(db, cfg)).get("verified"):
        channels.append("email")
    if user.whatsapp_number and user.whatsapp_verified and await whatsapp_ready(db, cfg):
        channels.append("whatsapp")
    return channels


CONTACT_PREFIX = "security.contact_approval."


async def contact_link(
    db: AsyncSession, cfg: Settings, user: User, channel: str, destination: str | None = None
) -> str:
    contact = destination or (user.email if channel == "email" else user.whatsapp_number)
    if not contact:
        raise HTTPException(422, "Save this user's contact first")
    token = secrets.token_urlsafe(32)
    key = CONTACT_PREFIX + hashlib.sha256(token.encode()).hexdigest()
    await save(
        db,
        key,
        {
            "user_id": user.id,
            "channel": channel,
            "contact": contact,
            "expires": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        },
    )
    return cfg.public_base_url.rstrip("/") + "/verify-contact?token=" + token


async def reserve_green(db: AsyncSession, config: dict[str, Any], recipient: str) -> None:
    from app.alerts.pacing import reserve
    from app.jobs.queue import DeferredError

    try:
        await reserve(db, f"greenapi:{config['instance_id']}", recipient, authentication=True)
    except DeferredError as exc:
        raise HTTPException(
            429,
            f"WhatsApp code limit reached. Retry in {int(exc.delay) + 1} seconds, or use email.",
        ) from None


async def send_green_code(
    config: dict[str, Any], recipient: str, code: str, approval_url: str | None = None
) -> None:
    # The token is part of GREEN-API's URL: never return provider errors or log the URL.
    base = f"{config['api_url']}/waInstance{config['instance_id']}"
    token = config["token"]
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        state = await client.get(f"{base}/getStateInstance/{token}")
        state.raise_for_status()
        if state.json().get("stateInstance") != "authorized":
            raise HTTPException(503, "GreenAPI WhatsApp instance is not connected")
        buttons = [
            {"type": "copy", "buttonId": "copy-code", "buttonText": "Copy code", "copyCode": code}
        ]
        if approval_url:
            buttons = [
                {
                    "type": "url",
                    "buttonId": "approve-contact",
                    "buttonText": "Approve WhatsApp",
                    "url": approval_url,
                }
            ]
        response = await client.post(
            f"{base}/sendInteractiveButtons/{token}",
            json={
                "chatId": recipient.lstrip("+") + "@c.us",
                "header": (
                    "Approve your Iris WhatsApp number"
                    if approval_url
                    else "Iris verification code"
                ),
                "body": (
                    "Confirm this WhatsApp number for your Iris account by opening the link "
                    f"below and selecting Approve contact:\n{approval_url}"
                    if approval_url
                    else f"Your Iris verification code is: {code}"
                ),
                "footer": (
                    "Approval link expires in 30 minutes."
                    if approval_url
                    else "Expires in 5 minutes. Do not share this code."
                ),
                "buttons": buttons,
            },
        )
        response.raise_for_status()
        if not response.json().get("idMessage"):
            raise HTTPException(503, "GreenAPI did not accept the verification message")


def smtp_message(
    config: dict[str, Any], recipient: str, code: str, approval_url: str | None = None
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = recipient
    if approval_url:
        from html import escape

        message["Subject"] = "Approve your Iris email address"
        message.set_content(
            "Confirm this email address for your Iris account by opening the link below "
            "and selecting Approve contact.\n\n"
            f"{approval_url}\n\nThis link expires in 30 minutes. "
            "If you did not request it, ignore this email."
        )
        message.add_alternative(
            "<html><body><h1>Approve your Iris email address</h1>"
            "<p>Confirm this email address for your Iris account. Open the link below "
            "and select Approve contact.</p>"
            f'<p><a href="{escape(approval_url, quote=True)}">Approve your email</a></p>'
            "<p>This link expires in 30 minutes.</p>"
            "<p>If you did not request it, ignore this email.</p></body></html>",
            subtype="html",
        )
        return message
    message["Subject"] = "Your Iris verification code"
    message.set_content(
        f"Your Iris verification code is: {code}\n\n"
        "Enter this code to sign in. It expires in 5 minutes. "
        "If you did not request it, ignore this email."
    )
    message.add_alternative(
        "<html><body><h1>Iris account verification</h1><p>Your verification code is:</p>"
        f'<p style="font-size:32px;font-weight:bold;letter-spacing:6px" dir="ltr">{code}</p>'
        "<p>Enter this code to sign in. It expires in 5 minutes.</p>"
        "<p>If you did not request it, ignore this email.</p></body></html>",
        subtype="html",
    )
    return message


def send_smtp(
    config: dict[str, Any], recipient: str, code: str, approval_url: str | None = None
) -> None:
    context = ssl.create_default_context()
    client = (
        smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
        if config["tls"] == "ssl"
        else smtplib.SMTP(config["host"], config["port"], timeout=15)
    )
    with client:
        if config["tls"] == "starttls":
            client.starttls(context=context)
        client.login(config["username"], config["password"])
        if client.send_message(smtp_message(config, recipient, code, approval_url)):
            raise smtplib.SMTPException("Recipient rejected")


async def deliver(db: AsyncSession, cfg: Settings, user: User, channel: str, code: str) -> None:
    config = await smtp_config(db, cfg)
    if channel not in await available_channels(db, cfg, user):
        raise HTTPException(
            422, "Approve this contact and test its delivery provider before using 2FA"
        )
    try:
        if channel == "email":
            if not user.email:
                raise HTTPException(422, "No email configured for this user")
            await asyncio.to_thread(send_smtp, config, user.email, code)
        else:
            green = await green_api_config(db, cfg)
            if not green.get("verified") or not user.whatsapp_number:
                raise HTTPException(
                    503, "Test GreenAPI and configure your personal WhatsApp number"
                )
            await reserve_green(db, green, user.whatsapp_number)
            await send_green_code(green, user.whatsapp_number, code)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Verification code delivery failed. Try again later.") from None
