"""Alert message text (spec 9.2) and the body-bound signed alert link.

The link's signature covers the alert id AND the whole message body above it, so a valid
signature validates only the exact text it was made for. A kid cannot paste a harmful message
under a copied link, nor reuse the signature of one alert on different text.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app.alerts import ALERT_PREFIX

MAX_QUOTE = 500
WITHHELD = "Content withheld (sexual content). Review the chat directly."
# The link must be the LAST line: anything typed after it would not be covered by the signature.
_LINK_RE = re.compile(r"\n\nOpen: \S*/alerts/(\d+)\?s=([0-9a-f]{16})\Z")
_NOTICE_RE = re.compile(r"\n\nOpen: \S*/\?iris_notice=([0-9a-f]{16})\Z")


def alert_signature(key: bytes, alert_id: int, body: str) -> str:
    digest = hashlib.sha256(body.encode()).hexdigest()
    return hmac.new(key, f"alert:{alert_id}:{digest}".encode(), hashlib.sha256).hexdigest()[:16]


def alert_link(base_url: str, key: bytes, alert_id: int, body: str) -> str:
    return f"{base_url}/alerts/{alert_id}?s={alert_signature(key, alert_id, body)}"


def with_signed_link(body: str, base_url: str, key: bytes, alert_id: int) -> str:
    body = body + "\n\nSent by Iris · Server: " + urlsplit(base_url).netloc
    return f"{body}\n\nOpen: {alert_link(base_url, key, alert_id, body)}"


def is_own_alert(text: str, key: bytes) -> bool:
    """True only for the exact text Iris produced: prefix, body, and a signature over that body."""
    if not text.startswith(ALERT_PREFIX):
        return False
    notice = _NOTICE_RE.search(text)
    if notice is not None:
        return hmac.compare_digest(notice.group(1), alert_signature(key, 0, text[: notice.start()]))
    m = _LINK_RE.search(text)
    if m is None:
        return False
    body = text[: m.start()]
    return hmac.compare_digest(m.group(2), alert_signature(key, int(m.group(1)), body))


def with_signed_dashboard(body: str, base_url: str, key: bytes) -> str:
    """Operational notices open Home and still cannot be re-ingested as child messages."""
    body = ALERT_PREFIX + " " + body + "\n\nSent by Iris · Server: " + urlsplit(base_url).netloc
    return f"{body}\n\nOpen: {base_url.rstrip('/')}/?iris_notice={alert_signature(key, 0, body)}"


def make_quote(message_type: str, text: str | None, transcript: str | None) -> str:
    """The quoted content: transcripts get 🎤, image captions 🖼️, bare images `[image]`."""
    if transcript and not text:
        body = f"🎤 {transcript}"
    elif transcript and text:
        body = f"🎤 {transcript}\n{text}"
    elif text and message_type in ("image", "sticker", "video"):
        body = f"🖼️ {text}"
    elif text:
        body = text
    else:
        body = f"[{message_type}]"
    return body if len(body) <= MAX_QUOTE else body[: MAX_QUOTE - 1] + "…"


@dataclass(frozen=True)
class MediaFact:
    media_id: int
    kind: str  # image | audio | video
    size_bytes: int


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


@dataclass(frozen=True)
class AlertFacts:
    alert_id: int
    kid_names: list[str]
    chat_name: str | None
    is_group: bool
    sender_name: str | None
    from_me: bool
    categories: list[str]  # most severe first
    max_score: float
    sent_at: datetime
    quote: str | None  # None when redacted
    message_id: int | None = None
    verdict: str | None = None
    review_reason: str | None = None
    more_suppressed: int = 0
    media: "MediaFact | None" = None  # a kept copy of the media (never set for a redacted alert)


def format_alert(
    f: AlertFacts, timezone: str, base_url: str, key: bytes, *, style: str = "detailed"
) -> str:
    when = f.sent_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))  # stored as naive UTC
    local = when.astimezone(ZoneInfo(timezone))
    if style == "summary":

        def one_line(value: str) -> str:
            return " ".join(value.split())[:160]

        action = "Needs your review" if f.verdict == "review" else "Check in with your child"
        lines = [
            ALERT_PREFIX,
            "",
            action,
            "",
            "Child: " + one_line(", ".join(f.kid_names) or "Unknown"),
            "Chat: "
            + one_line(f.chat_name or "Unnamed chat")
            + (" (group)" if f.is_group else " (contact)"),
            "Time: " + local.strftime("%d/%m %H:%M"),
            "",
            "Iris could not assess this message."
            if f.verdict == "review"
            else "Iris flagged a possible concern. Review the context before deciding.",
            "Open Iris to view details and mark it reviewed.",
        ]
        if f.more_suppressed:
            lines.append(
                f"{f.more_suppressed} additional alerts in this chat since the last notification."
            )
        return with_signed_link("\n".join(lines), base_url, key, f.alert_id)
    top, others = f.categories[0], f.categories[1:]
    category = (top if f.verdict == "review" else f"{top} ({f.max_score:.2f})") + (
        f", {', '.join(others)}" if others else ""
    )
    sender = (f.sender_name or "?") + (" (your kid)" if f.from_me else "")
    lines = [
        ALERT_PREFIX,
        "A message to check together",
        "",
        f"Kid: {', '.join(f.kid_names)}",
        f"Chat: {f.chat_name or '?'} ({'group' if f.is_group else 'direct'})",
        f"From: {sender}",
        f"Category: {category}",
        f"Time: {local.strftime('%d/%m %H:%M')}",
        "",
        WITHHELD if f.quote is None else "💬 Message\n" + f.quote,
    ]
    if f.message_id is not None:
        lines.insert(1, f"Alert: #{f.alert_id} · Message: #{f.message_id}")
    if f.verdict == "review":
        lines.insert(1, "Status: Needs parent review; not a harmful verdict")
        if f.review_reason:
            lines.insert(2, "Reason: " + f.review_reason)
    if f.media is not None and f.quote is not None:
        # In the body, before the signed link, so the signature covers it. It opens a portal page
        # that needs a login; the file itself is never reachable from this text alone.
        lines += [
            "",
            f"📎 Media kept ({f.media.kind}, {human_size(f.media.size_bytes)}): "
            f"{base_url}/media/{f.media.media_id}",
        ]
    if f.more_suppressed:
        lines += ["", f"+{f.more_suppressed} more alerts in this chat since last notification"]
    return with_signed_link("\n".join(lines), base_url, key, f.alert_id)


CHANGE_TEXT = {
    "edited": "was edited by the sender",
    "revoked": "was deleted for everyone by the sender",
}


def format_change_notice(kind: str, f: AlertFacts, timezone: str, base_url: str, key: bytes) -> str:
    """Follow-up after an alerted message changed. It never quotes content, so it is safe for
    redacted alerts too; the signed link opens the alert, where the portal shows the history."""
    when = f.sent_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))
    local = when.astimezone(ZoneInfo(timezone))
    sender = (f.sender_name or "?") + (" (your kid)" if f.from_me else "")
    lines = [
        ALERT_PREFIX,
        f"Update: the message from alert #{f.alert_id} {CHANGE_TEXT[kind]}.",
        f"Kid: {', '.join(f.kid_names)}",
        f"Chat: {f.chat_name or '?'} ({'group' if f.is_group else 'direct'})",
        f"From: {sender}",
        f"Time: {local.strftime('%d/%m %H:%M')}",
    ]
    return with_signed_link("\n".join(lines), base_url, key, f.alert_id)
