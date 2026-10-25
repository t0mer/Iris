"""Alert transports share recipient checkpoints, while authentication keeps its own lane."""

import asyncio
import base64
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.readiness import delivery_readiness
from app.config import get_settings
from app.db.models import Instance
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.crypto import decrypt
from app.security.two_factor import green_api_config, smtp_config
from app.settings_store import get_secret, get_setting


@lru_cache(maxsize=1)
def _preview_thumbnail() -> str | None:
    try:
        preview = Path(__file__).resolve().parents[1] / "assets" / "iris-preview.jpg"
        return base64.b64encode(preview.read_bytes()).decode("ascii")
    except OSError:
        return None


class _CredentialURLFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if "api.telegram.org/bot" in record.getMessage() or "/waInstance" in record.getMessage():
            record.msg, record.args = "Notification HTTP request (credential URL redacted)", ()
        return True


logging.getLogger("httpx").addFilter(_CredentialURLFilter())


def send_email(config: dict[str, Any], address: str, text: str) -> None:
    message = EmailMessage()
    message["From"], message["To"] = config["sender"], address
    message["Subject"] = "Iris family alert"
    message.set_content(text)
    parts = []
    for part in text.split("\n\n"):
        style = "margin:0 0 16px;white-space:pre-wrap"
        if part.startswith("💬 Message"):
            style += ";background:#e8f3ec;border-radius:12px;padding:16px"
        parts.append("<p style='" + style + "'>" + escape(part) + "</p>")
    last = text.rsplit("\n", 1)[-1]
    if last.startswith("Open: https://") or last.startswith("Open: http://"):
        parts.append(
            "<a style='color:#25735a' href='"
            + escape(last[6:], quote=True)
            + "'>Open the conversation in Iris</a>"
        )
    paragraphs = "".join(parts)
    message.add_alternative(
        "<html><body style='margin:0;background:#f3f6f4;font-family:Segoe UI,Arial,sans-serif;"
        "color:#25332d'>"
        "<div style='max-width:560px;margin:24px auto;background:white;border-radius:16px;"
        "padding:28px;"
        "font-size:16px;font-weight:400;line-height:1.65'>"
        "<h1 style='font-size:22px;font-weight:500;margin:0 0 20px'>Iris · Family update</h1>"
        + paragraphs
        + "</div></body></html>",
        subtype="html",
    )
    context = ssl.create_default_context()
    connection = (
        smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
        if config["tls"] == "ssl"
        else smtplib.SMTP(config["host"], config["port"], timeout=15)
    )
    with connection:
        if config["tls"] == "starttls":
            connection.starttls(context=context)
        connection.login(config["username"], config["password"])
        if connection.send_message(message):
            raise OpenWAError(400, "Email recipient rejected")


async def configured(db: AsyncSession, channel: str | None = None) -> bool:
    return (await delivery_readiness(db, channel)).ready


class ChannelClient:
    def __init__(
        self,
        channel: str,
        sender: Instance | None,
        config: dict[str, Any],
        contacts: dict[str, dict[str, str]],
        key: bytes,
        destinations: dict[str, str] | None = None,
        eligibility_errors: dict[str, str] | None = None,
    ):
        self.buttons: list[dict[str, str]] = []
        self.channel, self.config, self.contacts = channel, config, contacts
        self.destinations = destinations
        self.eligibility_errors = eligibility_errors or {}
        self.openwa = None
        if channel == "openwa" and sender and sender.openwa_api_key_enc:
            self.openwa = OpenWAClient(
                sender.openwa_base_url, decrypt(key, sender.openwa_api_key_enc)
            )
        self.session_id = sender.openwa_instance_id if sender else ""
        self.sender_key = (
            f"openwa:{sender.id}"
            if channel == "openwa" and sender
            else f"alerts:greenapi:{config.get('instance_id', '')}"
            if channel == "greenapi"
            else f"alerts:{channel}"
        )

    async def aclose(self) -> None:
        if self.openwa:
            await self.openwa.aclose()

    async def send_text(self, _: str, target: str, text: str) -> None:
        contact = self.contacts.get(target, {})
        if self.destinations is not None:
            destination = self.destinations.get(target)
            if destination is None:
                raise OpenWAError(
                    400,
                    self.eligibility_errors.get(
                        target, "Recipient is no longer eligible for this channel"
                    ),
                )
            if self.channel in ("openwa", "greenapi"):
                target = destination
            elif self.channel == "smtp":
                contact = {**contact, "email": destination}
            elif self.channel == "telegram":
                contact = {**contact, "telegram_chat_id": destination}
        if self.channel in ("openwa", "greenapi") and target.startswith("email:"):
            raise OpenWAError(400, "This parent has no WhatsApp destination; use email alerts")
        if self.channel == "openwa":
            if not self.openwa:
                raise OpenWAError(401, "OpenWA sender unavailable")
            await self.openwa.send_text(self.session_id, target, text)
            return
        if self.channel == "smtp":
            address = contact.get("email") or (
                target.removeprefix("email:") if target.startswith("email:") else None
            )
            if not address:
                raise OpenWAError(400, "Parent email is missing")
            try:
                await asyncio.to_thread(send_email, self.config, address, text)
            except smtplib.SMTPAuthenticationError:
                raise OpenWAError(401, "SMTP authorization rejected") from None
            except smtplib.SMTPRecipientsRefused:
                raise OpenWAError(400, "Email recipient rejected") from None
            except (OSError, smtplib.SMTPException):
                raise OpenWAError(None, "Email delivery status uncertain") from None
            return
        if self.channel == "telegram":
            chat_id = contact.get("telegram_chat_id")
            if not chat_id:
                raise OpenWAError(400, "Parent Telegram chat ID is missing")
            url = f"https://api.telegram.org/bot{self.config['token']}/sendMessage"
            body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
            if self.buttons:
                body["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b["text"], "callback_data": b["id"]} for b in self.buttons]
                    ]
                }
        else:
            url = (
                f"{self.config['api_url']}/waInstance{self.config['instance_id']}"
                f"/sendMessage/{self.config['token']}"
            )
            body = {"chatId": target, "message": text}
            # Include the thumbnail in the request: private Iris hosts cannot be
            # fetched by WhatsApp's public preview crawler.
            iris_base = get_settings().public_base_url.rstrip("/")
            links = re.findall(r"https?://[^\s<>]+", text)
            iris_link = next(
                (
                    link
                    for link in reversed(links)
                    if link == iris_base or link.startswith(iris_base + "/")
                ),
                None,
            )
            if iris_link and not self.buttons:
                thumbnail = await asyncio.to_thread(_preview_thumbnail)
                if thumbnail:
                    body.update(
                        {
                            "linkPreview": True,
                            "typePreview": "small",
                            "customPreview": {
                                "title": "Iris",
                                "description": "Open Iris to review your alerts securely.",
                                "link": iris_link,
                                "jpegThumbnail": thumbnail,
                            },
                        }
                    )
            if self.buttons:
                url = url.replace("/sendMessage/", "/sendInteractiveButtonsReply/")
                body = {
                    "chatId": target,
                    "body": text,
                    "footer": "Choose once. First parent response wins. Buttons expire in 4 days.",
                    "buttons": [
                        {"buttonId": b["id"], "buttonText": b["text"]} for b in self.buttons
                    ],
                }
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.post(url, json=body)
                if response.status_code >= 400:
                    raise OpenWAError(
                        response.status_code, "Notification provider rejected request"
                    )
                result = response.json()
                if self.channel == "telegram" and result.get("ok") is not True:
                    raise OpenWAError(
                        int(result.get("error_code", 400)), "Telegram rejected request"
                    )
                if self.channel == "greenapi" and not result.get("idMessage"):
                    raise OpenWAError(None, "GreenAPI delivery status uncertain")
        except (httpx.HTTPError, ValueError):
            raise OpenWAError(None, "Notification delivery status uncertain") from None


async def build_client(
    db: AsyncSession,
    sender: Instance | None,
    key: bytes,
    channel: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> ChannelClient:
    channel = channel or str(await get_setting(db, "alerts.channel"))
    cfg = get_settings()
    contacts = dict(
        (overrides or {}).get(
            "alerts.recipient_contacts", await get_setting(db, "alerts.recipient_contacts")
        )
    )
    readiness = await delivery_readiness(db, channel, overrides)
    if channel == "smtp":
        config = await smtp_config(db, cfg)
    elif channel == "greenapi":
        config = await green_api_config(db, cfg)
    elif channel == "telegram":
        config = {"token": await get_secret(db, "alerts.telegram_bot_token", key)}
    else:
        config = {}
    return ChannelClient(
        channel,
        sender,
        config,
        contacts,
        key,
        {r.target: r.destination for r in readiness.recipients if r.eligible and r.destination},
        {r.target: r.reason for r in readiness.recipients if r.reason},
    )
