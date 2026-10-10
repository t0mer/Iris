"""Backward-compatible recipient list stored in the existing string setting."""

import re

from app.config import get_settings


def recipients(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    for entry in re.split(r"[,;\n]", value):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("email:") or (
            "@" in entry and not entry.endswith(("@c.us", "@g.us", "@s.whatsapp.net"))
        ):
            from app.security.two_factor import email_address

            address = email_address(entry.removeprefix("email:"))
            if not address:
                raise ValueError("Enter a parent email address")
            canonical = "email:" + address.lower()
            if canonical not in result:
                result.append(canonical)
            continue
        if "@" not in entry:
            entry = re.sub(r"[\s()-]", "", entry).lstrip("+")
            if not re.fullmatch(r"\d{6,15}", entry):
                raise ValueError("Use international phone numbers separated by commas")
            if get_settings().local_safety_mode and entry.startswith("0"):
                raise ValueError("Use an international country code, without a leading local zero")
        elif not re.fullmatch(r"[\w.-]+@(?:c\.us|g\.us|s\.whatsapp\.net)", entry):
            raise ValueError("Invalid WhatsApp chat ID")
        canonical = entry if "@" in entry else entry + "@c.us"
        if canonical not in result:
            result.append(canonical)
    if len(result) > 10:
        raise ValueError("At most 10 alert recipients are supported")
    return result


def validate_recipients(value: str | None) -> str | None:
    return (
        ", ".join(
            target.removesuffix("@c.us") if re.fullmatch(r"\d+@c\.us", target) else target
            for target in recipients(value)
        )
        or None
    )
