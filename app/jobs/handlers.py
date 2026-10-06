"""Job handlers. `process_message` classifies one stored message (text, image, audio, video)."""

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.service import alert_on_harmful, alert_on_review, needs_redaction, redact_message
from app.chats import resolve_group_names
from app.classify.pipeline import PipelineOutcome, run_pipeline
from app.classify.stages import StageContext
from app.classify.thresholds import effective_thresholds
from app.db.models import Chat, Classification, Instance, Message
from app.jobs.queue import ClaimedJob, PermanentError
from app.media import ffmpeg
from app.media.fetch import MAX_AUDIO_SECONDS, MediaSkipped, download, job_tmpdir
from app.metrics import MESSAGES, STAGE_SECONDS, TRANSCRIBED_AUDIO_SECONDS
from app.openwa.client import OpenWAClient
from app.providers import Providers
from app.security.crypto import decrypt
from app.settings_store import get_secret, get_setting
from app.transcription.factory import build_transcriber

HarmfulHook = Callable[[AsyncSession, Message, PipelineOutcome], Awaitable[None]]


async def _no_alerts_yet(_db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    logger.info(
        "message {} is harmful ({}); alert service not wired", message.id, outcome.categories
    )


@dataclass
class Deps:
    session_factory: async_sessionmaker[AsyncSession]
    providers: Providers
    key_bytes: bytes
    data_dir: Path = Path("/data")
    public_base_url: str = "http://localhost:8080"
    on_harmful: HarmfulHook = field(default=alert_on_harmful)
    on_review: HarmfulHook = field(default=alert_on_review)


class Skip(Exception):
    """Nothing (more) to classify for this message; the reason is logged, never the content."""


def _media_ref(message: Message) -> dict[str, Any]:
    media = message.media
    if not isinstance(media, dict) or not media.get("message_ref"):
        raise PermanentError("message has no media reference")
    return media


async def _openwa_for(
    db: AsyncSession, media: dict[str, Any], key_bytes: bytes
) -> tuple[OpenWAClient, str]:
    instance = await db.get(Instance, media.get("instance_id"))
    if instance is None or not instance.openwa_api_key_enc:
        raise PermanentError("instance or its OpenWA API key is missing")
    client = OpenWAClient(instance.openwa_base_url, decrypt(key_bytes, instance.openwa_api_key_enc))
    return client, instance.openwa_instance_id


async def _fetch(db: AsyncSession, message: Message, deps: Deps, dest: Path) -> None:
    media = _media_ref(message)
    client, session_id = await _openwa_for(db, media, deps.key_bytes)
    try:
        await download(client, session_id, media["chat_id"], media["message_ref"], dest)
    finally:
        await client.aclose()


async def _image_data_url(db: AsyncSession, message: Message, deps: Deps, tmp: Path) -> str:
    raw, jpeg = tmp / "media.bin", tmp / "image.jpg"
    await _fetch(db, message, deps, raw)
    await ffmpeg.image_to_jpeg(raw, jpeg)
    data = await asyncio.to_thread(jpeg.read_bytes)
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


async def _transcribe(db: AsyncSession, deps: Deps, tmp: Path, message: Message) -> None:
    """Fill message.transcript from audio/voice/video; Skip when there is no speech."""
    if message.transcript:  # a retry must not pay for transcription twice
        return
    raw, mp3 = tmp / "media.bin", tmp / "audio.mp3"
    await _fetch(db, message, deps, raw)
    info = await ffmpeg.probe(raw)
    if not info.has_audio:
        raise Skip("video has no audio track")
    if info.duration is not None and info.duration > MAX_AUDIO_SECONDS:
        raise Skip(f"audio is {int(info.duration)}s, over the {MAX_AUDIO_SECONDS}s limit")
    await ffmpeg.extract_audio(raw, mp3)
    if info.duration is None:  # unknown from the container: measure the extracted audio instead
        info = await ffmpeg.probe(mp3)
        if info.duration is not None and info.duration > MAX_AUDIO_SECONDS:
            raise Skip(f"audio is {int(info.duration)}s, over the {MAX_AUDIO_SECONDS}s limit")
    transcriber = await build_transcriber(db, deps.key_bytes)
    try:
        result = await transcriber.transcribe(mp3, "audio/mpeg")
    finally:
        await transcriber.aclose()
    if info.duration:
        TRANSCRIBED_AUDIO_SECONDS.labels(transcriber.name).inc(info.duration)
    if not result.text:
        raise Skip("empty transcript")
    message.transcript = result.text
    await db.commit()  # persisted before moderation, so searches and retries see it


@dataclass
class Prepared:
    image: str | None = None
    # Why the media could not be examined (the caption may still be). Never silently "safe".
    problem: Exception | None = None


async def _prepare(db: AsyncSession, job: ClaimedJob, deps: Deps, message: Message) -> Prepared:
    """Fetch/convert media as needed."""
    if message.type in ("text", "document", "other"):
        return Prepared()  # only text (or a caption/filename) can be moderated
    try:
        async with job_tmpdir(deps.data_dir, job.id) as tmp:
            if message.type in ("image", "sticker"):
                return Prepared(image=await _image_data_url(db, message, deps, tmp))
            await _transcribe(db, deps, tmp, message)
            return Prepared()
    except (Skip, MediaSkipped, PermanentError) as exc:
        if not message.text:
            raise
        # The caption is still worth moderating: a harmful caption must never be lost
        # just because the attachment could not be fetched, converted or transcribed.
        logger.info("message {}: {}; moderating the caption only", message.id, exc)
        return Prepared(problem=exc)


def _persist(db: AsyncSession, message: Message, outcome: PipelineOutcome) -> None:
    for r in outcome.results:
        db.add(
            Classification(
                message_id=message.id,
                stage=r.stage,
                input_kind=r.input_kind,
                model=r.model,
                scores=r.scores,
                flagged_categories=r.flagged_categories,
                band=r.band,
                context_message_ids=r.context_message_ids,
                latency_ms=r.latency_ms,
            )
        )


async def process_message(job: ClaimedJob, deps: Deps) -> None:
    message_id = job.payload.get("message_id")
    if not isinstance(message_id, int):
        raise PermanentError("job payload has no message_id")
    async with deps.session_factory() as db:
        message = await db.get(Message, message_id)
        if message is None:
            raise PermanentError("message no longer exists")
        if message.redacted:
            message.status = "skipped"  # redacted content is never reprocessed
            await db.commit()
            return

        message.status = "processing"
        await db.execute(delete(Classification).where(Classification.message_id == message.id))
        await db.commit()
        # Name the group before anything quotes it (an alert snapshots the chat name). Best effort.
        chat = await db.get(Chat, message.chat_id)
        if chat is not None and chat.is_group and not chat.name:
            await resolve_group_names(deps.session_factory, deps.key_bytes, chat_id=chat.id)
            await db.refresh(chat)

        legacy = job.payload.get("media")  # jobs queued before the media column existed
        if message.media is None and isinstance(legacy, dict):
            message.media = {**legacy, "instance_id": job.payload.get("instance_id")}
            await db.commit()

        try:
            prepared = await _prepare(db, job, deps, message)
        except (Skip, MediaSkipped) as exc:
            logger.info("message {} skipped: {}", message.id, exc)
            message.status = "skipped"
            await db.commit()
            return

        api_key = await get_secret(db, "openai.api_key", deps.key_bytes)
        if not api_key:
            raise PermanentError("OpenAI API key is not configured")
        ctx = StageContext(
            db=db,
            moderator=deps.providers.moderation(api_key),
            model=str(await get_setting(db, "classification.model")),
            thresholds=effective_thresholds(await get_setting(db, "classification.thresholds")),
            context_window_size=int(await get_setting(db, "classification.context_window_size")),
            context_max_age=timedelta(
                hours=int(await get_setting(db, "classification.context_max_age_hours"))
            ),
            image_data_url=prepared.image,
        )
        try:
            outcome = await run_pipeline(message, ctx)
        except ValueError:
            message.status = "skipped"  # nothing to classify (no text, transcript or image)
            await db.commit()
            return

        _persist(db, message, outcome)
        problem = prepared.problem
        if problem is not None and outcome.verdict != "harmful":
            # Only the caption was examined: do not present the message as classified.
            message.verdict = None
            message.status = "failed" if isinstance(problem, PermanentError) else "skipped"
            await db.commit()
            if isinstance(problem, PermanentError):
                raise problem  # visible on the Jobs page, retryable once the cause is fixed
            return
        message.verdict = outcome.verdict
        message.status = "done"
        if outcome.results:
            last = outcome.results[-1]
            if needs_redaction(message.type, last.high_categories, last.flagged_categories):
                # Withhold now, in the same commit as the verdict: a message awaiting review (or
                # with alerts off) must not sit in the DB, search index or portal unredacted.
                redact_message(message)
                logger.warning(
                    "message {} redacted at classification; content withheld", message.id
                )
        await db.commit()
        # Metrics only after the commit, so a retried job is never counted twice.
        MESSAGES.labels(message.type, outcome.verdict).inc()
        for r in outcome.results:
            STAGE_SECONDS.labels(r.stage).observe(r.latency_ms / 1000)
        logger.info(
            "message {} classified: type={} verdict={} stages={}",
            message.id,
            message.type,
            outcome.verdict,
            [r.stage for r in outcome.results],
        )
        hook = {"harmful": deps.on_harmful, "review": deps.on_review}.get(outcome.verdict)
        if hook is not None:
            try:
                await hook(db, message, outcome)
            except Exception:
                # Classification is done and committed: a failing hook must not mark the message
                # failed or re-run the pipeline. Alert delivery has its own retry.
                logger.exception("alert hook failed for message {}", message.id)
