"""Message search: SQLite FTS5 where it exists, case-insensitive substring matching elsewhere."""

import re

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message

# Snippet markers (control chars, never HTML): the UI splits on them, so content is never
# rendered as markup.
MARK_START, MARK_END = "\x02", "\x03"
_TOKEN = re.compile(r"[\w]+", re.UNICODE)
SEARCH_LIMIT = 5000
_CONTEXT = 60  # characters kept on each side of the first hit in a substring snippet


def search_tokens(q: str) -> list[str]:
    """The words of a user's query; punctuation is ignored."""
    return _TOKEN.findall(q)


def fts_query(q: str) -> str | None:
    """User text -> safe FTS5 query: every word is a quoted prefix term (AND)."""
    tokens = search_tokens(q)
    return " ".join(f'"{t}"*' for t in tokens) or None


async def find_matches(db: AsyncSession, tokens: list[str]) -> dict[int, str]:
    """Message id -> snippet (hits wrapped in the markers) for every word being present."""
    if not tokens:
        return {}  # an empty query must never mean "everything"
    if db.get_bind().dialect.name == "sqlite":
        return await _sqlite_fts(db, tokens)
    return await _substring(db, tokens)


async def _sqlite_fts(db: AsyncSession, tokens: list[str]) -> dict[int, str]:
    match = " ".join(f'"{t}"*' for t in tokens)
    rows = await db.execute(
        text(
            "SELECT rowid, snippet(messages_fts, -1, :a, :b, '…', 14) FROM messages_fts "
            "WHERE messages_fts MATCH :m ORDER BY rank LIMIT :lim"
        ),
        {"a": MARK_START, "b": MARK_END, "m": match, "lim": SEARCH_LIMIT},
    )
    return {int(r[0]): str(r[1]) for r in rows}


def _like(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _substring(db: AsyncSession, tokens: list[str]) -> dict[int, str]:
    """Each word may appear in the text, the transcript or the sender's name, anywhere in a word.

    Withheld (redacted) messages never match, like their blanked FTS rows.
    """
    if not tokens:
        return {}
    fields = (Message.text, Message.transcript, Message.sender_name)
    cond = and_(
        *(or_(*(f.ilike(_like(t), escape="\\") for f in fields)) for t in tokens),
        Message.redacted.is_(False),
    )
    rows = await db.execute(
        select(Message.id, Message.text, Message.transcript, Message.sender_name)
        .where(cond)
        .order_by(Message.sent_at.desc(), Message.id.desc())
        .limit(SEARCH_LIMIT)
    )
    pattern = re.compile(
        "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True)), re.I
    )
    return {
        int(mid): _snippet(pattern, [text_, transcript, sender])
        for mid, text_, transcript, sender in rows
    }


def _snippet(pattern: "re.Pattern[str]", fields: list[str | None]) -> str:
    for value in fields:
        if not value:
            continue
        first = pattern.search(value)
        if first is None:
            continue
        start = max(0, first.start() - _CONTEXT)
        end = min(len(value), first.end() + _CONTEXT)
        piece = value[start:end]
        marked = pattern.sub(lambda m: f"{MARK_START}{m.group(0)}{MARK_END}", piece)
        return ("…" if start > 0 else "") + marked + ("…" if end < len(value) else "")
    return ""
