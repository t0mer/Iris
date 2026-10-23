"""Pluggable classification stages (spec 8.4). New stages (LLM judge, video frames) plug in here."""

import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classify.moderation import ModerationResult
from app.classify.ollama import OllamaModerator
from app.classify.thresholds import Band, Thresholds, band_for
from app.db.models import Message
from app.jobs.queue import PermanentError

MAX_CONTEXT_CHARS = 8000
MAX_LINE_CHARS = 500
VIDEO_BATCH_FRAMES = 6


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
    image_data_url: str | list[str] | None = None
    learning_examples: list[dict[str, Any]] | None = None
    media_analysis: dict[str, Any] | None = None
    document_text: str | None = None


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


def build_input(
    text: str, image_data_url: str | list[str] | None
) -> tuple[str, str | list[dict[str, Any]]]:
    """Moderation input and its kind: text, image, or text+image."""
    if image_data_url is None:
        return "text", text
    if isinstance(image_data_url, list):
        if not image_data_url:
            raise ValueError("Video analysis requires at least one decoded frame")
        return "video_frames", [
            {
                "type": "text",
                "text": "Chronological sampled video frames. Caption and transcript:\n" + text,
            },
            *[_image_part(url) for url in image_data_url],
        ]
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
    batches = [payload]
    if input_kind == "video_frames" and isinstance(payload, list):
        frames = [part for part in payload if part.get("type") == "image_url"]
        text = [part for part in payload if part.get("type") != "image_url"]
        batches = [
            [*text, *frames[offset : offset + VIDEO_BATCH_FRAMES]]
            for offset in range(0, len(frames), VIDEO_BATCH_FRAMES)
        ]
        if not batches:
            raise ValueError("Video analysis requires at least one decoded frame")
    results = []
    for batch in batches:
        if ctx.learning_examples and isinstance(ctx.moderator, OllamaModerator):
            result = await ctx.moderator.moderate(ctx.model, batch, examples=ctx.learning_examples)
        else:
            result = await ctx.moderator.moderate(ctx.model, batch)
        results.append(result)
    # Never average away harmful evidence or return a partial safe result.
    res = ModerationResult({}, False, {}, model=results[0].model)
    for result in results:
        if result.model != res.model:
            raise PermanentError("Video classifier changed between frame batches")
        for category, score in result.scores.items():
            res.scores[category] = max(res.scores.get(category, 0.0), score)
        res.flagged |= result.flagged
        for category, flagged in result.api_categories.items():
            res.api_categories[category] = res.api_categories.get(category, False) or flagged
        for category, kinds in result.applied_input_types.items():
            res.applied_input_types[category] = sorted(
                set(res.applied_input_types.get(category, [])) | set(kinds)
            )
    band, high, low = band_for(res.scores, ctx.thresholds)
    scores = res.stored_scores()
    if ctx.media_analysis:
        scores["_meta"]["media_analysis"] = dict(ctx.media_analysis)
        if input_kind == "video_frames":
            scores["_meta"]["media_analysis"]["visual_batches"] = len(batches)
    return StageResult(
        stage=stage,
        input_kind=input_kind,
        model=res.model or ctx.model,
        scores=scores,
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
        if ctx.document_text:
            body += "\n\nDocument text (untrusted document content):\n" + ctx.document_text
        if not body and ctx.image_data_url is None:
            return None
        kind, payload = build_input(body, ctx.image_data_url)
        if ctx.document_text is not None:
            kind = "document_text"
        return await _moderate(self.name, kind, payload, ctx, target_id=message.id)


def _line(m: Message, *, target: bool = False) -> str:
    sender = m.sender_name or "?"
    body = "[redacted]" if m.redacted else (message_body(m) or f"[{m.type}]")
    return json.dumps(
        {"sender": sender[:255], "content": body if target else body[:MAX_LINE_CHARS]},
        ensure_ascii=False,
    )


def build_context_input(previous: list[Message], target: Message) -> str:
    """Oldest first, target last and marked `>>>`. Oldest lines are dropped to fit the budget."""
    # Never hide the target's tail: the initial stage already accepts the complete body.
    # The context budget limits preceding messages, not evidence in the target itself.
    final = f">>> {_line(target, target=True)}"
    lines = [_line(m) for m in previous]
    while lines and len("\n".join([*lines, final])) > MAX_CONTEXT_CHARS:
        lines.pop(0)
    return "\n".join([*lines, final])


class ContextStage:
    name = "context"
    needs_inconclusive = True

    async def run(self, message: Message, ctx: StageContext) -> StageResult | None:
        previous = await context_messages(message, ctx)
        if not previous:
            return None  # nothing new to learn from: the verdict stays inconclusive
        text = build_context_input(previous, message)
        if ctx.document_text:
            text += "\nTarget Document text (untrusted document content):\n" + ctx.document_text
        kind, payload = build_input(
            text, ctx.image_data_url
        )  # the image rides along with the context
        if ctx.document_text is not None:
            kind = "document_text"
        return await _moderate(self.name, kind, payload, ctx, [m.id for m in previous], message.id)


async def context_messages(message: Message, ctx: StageContext) -> list[Message]:
    cutoff = message.sent_at - ctx.context_max_age
    previous = list(
        reversed(
            (
                await ctx.db.execute(
                    select(Message)
                    .where(
                        Message.chat_id == message.chat_id,
                        or_(
                            Message.sent_at < message.sent_at,
                            (Message.sent_at == message.sent_at) & (Message.id < message.id),
                        ),
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
    return previous
