"""Pluggable classification stages (spec 8.4). New stages (LLM judge, video frames) plug in here."""

import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.moderation import ModerationResult
from app.classify.ollama import OllamaModerator
from app.classify.thresholds import Band, Thresholds, band_for
from app.db.models import Message

MAX_CONTEXT_CHARS = 8000
MAX_LINE_CHARS = 500


class Moderator(Protocol):
    async def moderate(
        self, model: str, input_: str | list[dict[str, Any]]
    ) -> ModerationResult: ...


@dataclass
class StageContext:
    db: AsyncSession
    moderator: Moderator
    model: str
    thresholds: Thresholds
    context_window_size: int
    context_max_age: timedelta
    # JPEG data URL of the message's image/sticker, when it has one.
    image_data_url: str | None = None
    learning_examples: list[dict[str, Any]] | None = None


@dataclass
class StageResult:
    stage: str  # matches classifications.stage
    input_kind: str
    model: str
    scores: dict[str, Any]
    band: Band
    high_categories: list[str]
    flagged_categories: list[str]  # categories at or above their low threshold
    latency_ms: int
    context_message_ids: list[int] | None = None


class Stage(Protocol):
    name: str
    # Stages that refine an earlier result (like context) only run after an inconclusive one.
    needs_inconclusive: bool

    async def run(self, message: Message, ctx: StageContext) -> StageResult | None:
        """Return None when the stage does not apply to this message."""
        ...


def message_body(m: Message) -> str:
    """What was said: text/caption and, for voice/video, the transcript."""
    parts = [p for p in (m.text, m.transcript) if p]
    return "\n".join(parts).strip()


def _image_part(data_url: str) -> dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": data_url}}


def build_input(text: str, image_data_url: str | None) -> tuple[str, str | list[dict[str, Any]]]:
    """Moderation input and its kind: text, image, or text+image."""
    if image_data_url is None:
        return "text", text
    if not text:
        return "image", [_image_part(image_data_url)]
    return "text+image", [{"type": "text", "text": text}, _image_part(image_data_url)]


async def _moderate(
    stage: str,
    input_kind: str,
    payload: str | list[dict[str, Any]],
    ctx: StageContext,
    context_ids: list[int] | None = None,
    target_id: int | None = None,
) -> StageResult:
    started = time.perf_counter()
    if ctx.learning_examples and isinstance(ctx.moderator, OllamaModerator):
        res = await ctx.moderator.moderate(ctx.model, payload, examples=ctx.learning_examples)
    else:
        res = await ctx.moderator.moderate(ctx.model, payload)
    band, high, low = band_for(res.scores, ctx.thresholds)
    return StageResult(
        stage=stage,
        input_kind=input_kind,
        model=res.model or ctx.model,
        scores=res.stored_scores(),
        band=band,
        high_categories=high,
        flagged_categories=low,
        latency_ms=int((time.perf_counter() - started) * 1000),
        context_message_ids=context_ids,
    )


class ModerationStage:
    name = "moderation"
    needs_inconclusive = False

    async def run(self, message: Message, ctx: StageContext) -> StageResult | None:
        body = message_body(message)
        if not body and ctx.image_data_url is None:
            return None
        kind, payload = build_input(body, ctx.image_data_url)
        return await _moderate(self.name, kind, payload, ctx, target_id=message.id)


def _line(m: Message) -> str:
    sender = m.sender_name or "?"
    body = "[redacted]" if m.redacted else (message_body(m) or f"[{m.type}]")
    return json.dumps(
        {"sender": sender[:255], "content": body[:MAX_LINE_CHARS]}, ensure_ascii=False
    )


def build_context_input(previous: list[Message], target: Message) -> str:
    """Oldest first, target last and marked `>>>`. Oldest lines are dropped to fit the budget."""
    final = f">>> {_line(target)}"
    lines = [_line(m) for m in previous]
    while lines and len("\n".join([*lines, final])) > MAX_CONTEXT_CHARS:
        lines.pop(0)
    return "\n".join([*lines, final])


class ContextStage:
    name = "context"
    needs_inconclusive = True

    async def run(self, message: Message, ctx: StageContext) -> StageResult | None:
        cutoff = message.sent_at - ctx.context_max_age
        previous = list(
            reversed(
                (
                    await ctx.db.execute(
                        select(Message)
                        .where(
                            Message.chat_id == message.chat_id,
                            Message.id != message.id,
                            Message.revoked_at.is_(None),
                            Message.sent_at >= cutoff,
                            Message.sent_at <= message.sent_at,
                        )
                        .order_by(Message.sent_at.desc(), Message.id.desc())
                        .limit(ctx.context_window_size)
                    )
                )
                .scalars()
                .all()
            )
        )
        if not previous:
            return None  # nothing new to learn from: the verdict stays inconclusive
        text = build_context_input(previous, message)
        kind, payload = build_input(
            text, ctx.image_data_url
        )  # the image rides along with the context
        return await _moderate(self.name, kind, payload, ctx, [m.id for m in previous], message.id)
