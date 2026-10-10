"""One channel-specific recipient policy for settings, delivery and health.

Recipient keys remain stable across transports, preserving legacy lists and child
assignments. OpenWA and email contacts require current approval; standalone legacy
destinations remain usable without inventing approval records for them.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.recipients import recipients
from app.config import get_settings
from app.db.models import Instance, Setting, User
from app.security.two_factor import green_api_config, load, smtp_config
from app.settings_store import get_secret, get_setting

LABELS = {
    "openwa": "WhatsApp via OpenWA",
    "greenapi": "WhatsApp via GreenAPI",
    "smtp": "Email",
    "telegram": "Telegram",
}
BINDINGS_KEY = "alerts.recipient_users"


async def bind_recipient_users(db: AsyncSession) -> None:
    """Remember account identity before contacts change; removed targets lose their binding.

    Internal metadata, not an editable setting. Legacy standalone destinations
    keep working, but an account-linked number cannot silently turn into a
    standalone destination when that account changes its number.
    """
    targets = recipients(await get_setting(db, "alerts.recipient"))
    old = await load(db, BINDINGS_KEY, {})
    users = list(await db.scalars(select(User)))
    contacts = await get_setting(db, "alerts.recipient_contacts")
    bindings = {target: old[target] for target in targets if target in old}
    for target in targets:
        if target in bindings:
            continue
        for user in users:
            email = "email:" + user.email.strip().lower() if user.email else None
            phone = _phone(user)
            if target in (
                email,
                phone,
                phone.replace("@c.us", "@s.whatsapp.net") if phone else None,
            ) or (
                user.email
                and contacts.get(target, {}).get("email", "").lower() == user.email.lower()
            ):
                bindings[target] = user.id
                break
    row = await db.get(Setting, BINDINGS_KEY)
    if row is None:
        db.add(Setting(key=BINDINGS_KEY, value=bindings))
    else:
        row.value = bindings
    await db.flush()


@dataclass
class RecipientReadiness:
    target: str
    user_id: int | None
    name: str
    eligible: bool
    reason: str | None
    legacy: bool = False
    destination: str | None = None


@dataclass
class DeliveryReadiness:
    channel: str
    provider_ready: bool
    provider_error: str | None
    recipients: list[RecipientReadiness] = field(default_factory=list)
    users: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.provider_ready and any(r.eligible for r in self.recipients)

    @property
    def eligible_targets(self) -> list[str]:
        return [r.target for r in self.recipients if r.eligible]

    @property
    def error(self) -> str:
        errors = [self.provider_error] if self.provider_error else []
        if not self.eligible_targets:
            errors.append(f"No eligible recipients for {LABELS[self.channel]}.")
            errors.extend(f"{r.name}: {r.reason}" for r in self.recipients)
            if not self.recipients:
                errors.append("Add a parent recipient with a destination for this channel.")
        return " ".join(errors)

    def public(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "ready": self.ready,
            "eligible_count": len(self.eligible_targets),
            "invalid_count": sum(not r.eligible for r in self.recipients),
            "error": self.error if not self.ready else None,
        }


def _phone(user: User) -> str | None:
    return user.whatsapp_number.lstrip("+") + "@c.us" if user.whatsapp_number else None


async def delivery_readiness(
    db: AsyncSession, channel: str | None = None, overrides: dict[str, Any] | None = None
) -> DeliveryReadiness:
    overrides = overrides or {}

    async def value(key: str) -> Any:
        return overrides[key] if key in overrides else await get_setting(db, key)

    channel = channel or str(await value("alerts.channel"))
    cfg = get_settings()
    provider_error = None
    if channel == "openwa":
        sender_id = await value("alerts.sender_instance_id")
        sender = await db.get(Instance, sender_id) if sender_id else None
        if not sender or not sender.openwa_api_key_enc:
            provider_error = "Select an OpenWA sender with an API key."
    elif channel == "smtp":
        if not (await smtp_config(db, cfg)).get("verified"):
            provider_error = "Save and successfully test SMTP before choosing email alerts."
    elif channel == "greenapi":
        green = await green_api_config(db, cfg)
        if not green.get("verified"):
            provider_error = "Save and successfully test GreenAPI before choosing WhatsApp alerts."
    elif channel == "telegram":
        token = (
            overrides.get("alerts.telegram_bot_token")
            if "alerts.telegram_bot_token" in overrides
            else await get_secret(db, "alerts.telegram_bot_token", cfg.key_bytes)
        )
        if not token:
            provider_error = "Enter a Telegram bot token."
    else:
        raise ValueError("Unknown alert channel")
    result = DeliveryReadiness(channel, provider_error is None, provider_error)
    accounts = list(await db.scalars(select(User).order_by(User.id)))
    by_id = {user.id: user for user in accounts}
    bindings = await load(db, BINDINGS_KEY, {})
    by_target = {}
    for account in accounts:
        if account.email:
            by_target["email:" + account.email.strip().lower()] = account
        phone = _phone(account)
        if phone:
            by_target[phone] = account
            by_target[phone.replace("@c.us", "@s.whatsapp.net")] = account
    contacts = await value("alerts.recipient_contacts")
    assignments = await value("alerts.recipient_children")
    try:
        targets = recipients(await value("alerts.recipient"))
    except ValueError as exc:
        targets = []
        result.issues.append(str(exc))
    for target in targets:
        user: User | None = (
            by_id.get(bindings[target]) if target in bindings else by_target.get(target)
        )
        # A legacy phone can explicitly map to a registered email. It must not
        # become a way to bypass that account's destination approval.
        contact = contacts.get(target, {})
        if target not in bindings and user is None and contact.get("email"):
            user = by_target.get("email:" + contact["email"].lower())
        related = [target]
        if user:
            related += ["email:" + user.email.lower()] if user.email else []
            phone = _phone(user)
            if phone:
                related.append(phone)
        destination, reason = None, None
        if target in bindings and user is None:
            reason = "Recipient account was deleted. Remove or replace this recipient explicitly."
        elif user and user.role == "watch":
            reason = "Watch users do not receive parent alerts."
        elif channel in ("openwa", "greenapi"):
            destination = (
                _phone(user) if user else (None if target.startswith("email:") else target)
            )
            if not destination:
                reason = (
                    "No WhatsApp number. Adding a number is optional; "
                    "this user cannot receive WhatsApp alerts without one."
                )
            elif (
                channel == "greenapi"
                and destination
                == (await green_api_config(db, cfg)).get("sender_number", "").lstrip("+") + "@c.us"
            ):
                reason = "Recipient number is the GreenAPI sender. Use a different personal number."
            elif (
                channel == "openwa"
                and sender
                and sender.phone_number
                and destination == sender.phone_number.lstrip("+") + "@c.us"
            ):
                reason = "Recipient number is the OpenWA sender. Use a different personal number."
            elif channel == "openwa" and user and not user.whatsapp_verified:
                reason = "WhatsApp number is not approved. Approve the current number in Users."
        elif channel == "smtp":
            destination = (
                user.email
                if user
                else contact.get("email") or (target[6:] if target.startswith("email:") else None)
            )
            owner = by_target.get("email:" + destination.lower()) if destination else None
            if not destination:
                reason = "No email destination."
            elif owner and not owner.email_verified:
                reason = "Email address is not approved. Approve the current email in Users."
            elif owner and owner.role == "watch":
                reason = "Watch users do not receive parent alerts."
            elif user and (not owner or owner.id != user.id):
                reason = "Email destination does not match an approved user contact."
        else:
            destination = next(
                (
                    contacts.get(key, {}).get("telegram_chat_id")
                    for key in related
                    if contacts.get(key, {}).get("telegram_chat_id")
                ),
                None,
            )
            if not destination:
                reason = "No Telegram chat ID. Start the bot and save the parent's chat ID."
        if reason is None and target in assignments and not assignments[target]:
            reason = "No children assigned; alerts are paused for this recipient."
        result.recipients.append(
            RecipientReadiness(
                target,
                user.id if user else None,
                user.username if user else target,
                reason is None,
                reason,
                user is None,
                destination,
            )
        )
    for user in accounts:
        if user.role == "watch":
            continue
        selected = [r for r in result.recipients if r.user_id == user.id]
        reason = next((r.reason for r in selected if r.reason), None)
        eligible = any(r.eligible for r in selected)
        if not selected:
            if channel in ("openwa", "greenapi"):
                reason = (
                    "No WhatsApp number."
                    if not user.whatsapp_number
                    else "WhatsApp number is not approved."
                    if channel == "openwa" and not user.whatsapp_verified
                    else "Not selected as an alert recipient."
                )
            elif channel == "smtp":
                reason = (
                    "No email address."
                    if not user.email
                    else "Email address is not approved."
                    if not user.email_verified
                    else "Not selected as an alert recipient."
                )
            else:
                reason = "Not selected as an alert recipient; add a Telegram destination."
        result.users.append(
            {
                "id": user.id,
                "username": user.username,
                "selected": bool(selected),
                "eligible": eligible,
                "reason": None if eligible else reason,
            }
        )
    if provider_error:
        result.issues.append(provider_error)
    if not result.eligible_targets:
        result.issues.append(f"No eligible recipients for {LABELS[channel]}.")
    invalid = sum(not r.eligible for r in result.recipients)
    if invalid:
        checks = (
            "Check destinations and child assignments."
            if channel in ("greenapi", "telegram")
            else "Check destinations, approvals and child assignments."
        )
        result.issues.append(
            f"{invalid} selected recipient(s) cannot receive {LABELS[channel]} alerts. " + checks
        )
    return result
