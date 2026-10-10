"""Job handlers. `process_message` classifies one stored message (text, image, audio, video)."""

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.service import (
    alert_on_harmful,
    alert_on_review,
    create_alert,
    needs_redaction,
    redact_message,
    scores_from_classifications,
    wipe_revisions,
)
from app.chats import resolve_group_names
from app.classify.learning import compare
from app.classify.pipeline import PipelineOutcome, run_pipeline
from app.classify.stages import StageContext, message_body
from app.classify.thresholds import effective_thresholds
from app.config import get_settings
from app.db.models import Chat, Classification, Job, Message, MessageRevision, ReviewDataIssue
from app.jobs.queue import ClaimedJob, LostLeaseError, PermanentError, TransientError
from app.media import ffmpeg
from app.media.fetch import MAX_AUDIO_SECONDS, MediaSkipped, fetch_original, job_tmpdir
from app.media.keep import keep_media
from app.media.records import mark_purge
from app.metrics import MESSAGES, STAGE_SECONDS, TRANSCRIBED_AUDIO_SECONDS
from app.providers import Providers
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


async def _fetch(db: AsyncSession, message: Message, deps: Deps, dest: Path) -> str:
    return await fetch_original(db, message, deps.key_bytes, dest, recover=True)


async def _image_data_url(db: AsyncSession, message: Message, deps: Deps, tmp: Path) -> str:
    raw, jpeg = tmp / "media.bin", tmp / "image.jpg"
    await _fetch(db, message, deps, raw)
    await ffmpeg.image_to_jpeg(raw, jpeg)
    data = await asyncio.to_thread(jpeg.read_bytes)
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


async def _transcribe(
    db: AsyncSession, deps: Deps, tmp: Path, message: Message, job: ClaimedJob | None = None
) -> None:
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
    if job is not None:
        await _commit_message(db, job)
    else:
        await db.commit()  # standalone preparation


@dataclass
class Prepared:
    image: str | None = None
    # Why the media could not be examined (the caption may still be). Never silently "safe".
    problem: Exception | None = None


async def _prepare(db: AsyncSession, job: ClaimedJob, deps: Deps, message: Message) -> Prepared:
    """Fetch/convert media as needed."""
    if message.type == "other" and message.media is not None and get_settings().local_safety_mode:
        return Prepared(
            problem=PermanentError("Unknown message type; attachment cannot be analyzed")
        )
    if message.type == "document":
        return Prepared(problem=PermanentError("Document attachment requires manual review"))
    if message.type == "poll" and not (message.diagnostics or {}).get("has_poll_options"):
        return Prepared(
            problem=PermanentError(
                "Poll options were not provided by OpenWA; manual review required"
            )
        )
    if message.type in ("text", "other", "poll"):
        return Prepared()  # only text (or a caption/filename) can be moderated
    cfg = get_settings()
    try:
        async with job_tmpdir(deps.data_dir, job.id) as tmp:
            if message.type in ("image", "sticker"):
                return Prepared(image=await _image_data_url(db, message, deps, tmp))
            await _transcribe(db, deps, tmp, message, job)
            if cfg.local_safety_mode and message.type == "video":
                return Prepared(problem=PermanentError("video visuals require manual review"))
            return Prepared()
    except (Skip, MediaSkipped, PermanentError) as exc:
        if cfg.local_safety_mode:
            return Prepared(problem=exc)
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


_RANK = {"safe": 0, "review": 1, "harmful": 2}


async def _commit_message(db: AsyncSession, job: ClaimedJob) -> None:
    from app.jobs.queue import ensure_owned

    await ensure_owned(db, job)
    await db.commit()


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
            message.skip_reason = "Withheld content cannot be reprocessed"
            await _commit_message(db, job)
            return

        # An edit queues a second check while the first may still be running: wait for it, so
        # two checks never interleave their classifications and verdicts.
        busy = (
            await db.execute(
                select(Job.id).where(
                    Job.type == "process_message",
                    Job.status == "running",
                    Job.id < job.id,  # only the later job waits, so two can never block each other
                    Job.payload["message_id"].as_integer() == message.id,
                )
            )
        ).first()
        if busy is not None:
            raise TransientError("this message is already being checked")
        prior_verdict = message.verdict
        message.skip_reason = None
        message.review_reason = None
        # Only known content-free gateway system events may bypass moderation.
        if (
            message.raw_type in {"e2e_notification", "notification_template", "gp2", "revoked"}
            and not message.text
            and not message.transcript
            and message.media is None
        ):
            message.status = "skipped"
            message.verdict = None
            message.skip_reason = "Confirmed system event: " + message.raw_type
            await _commit_message(db, job)
            return
        message.status = "processing"
        await db.execute(delete(Classification).where(Classification.message_id == message.id))
        await _commit_message(db, job)
        # Name the group before anything quotes it (an alert snapshots the chat name). Best effort.
        chat = await db.get(Chat, message.chat_id)
        if chat is not None and chat.is_group and not chat.name:
            await resolve_group_names(deps.session_factory, deps.key_bytes, chat_id=chat.id)
            await db.refresh(chat)

        legacy = job.payload.get("media")  # jobs queued before the media column existed
        if message.media is None and isinstance(legacy, dict):
            message.media = {**legacy, "instance_id": job.payload.get("instance_id")}
            await _commit_message(db, job)

        try:
            prepared = await _prepare(db, job, deps, message)
        except (Skip, MediaSkipped) as exc:
            logger.info("message {} skipped: {}", message.id, exc)
            message.status = "skipped"
            message.verdict = None
            message.skip_reason = str(exc)[:255]
            await _commit_message(db, job)
            return

        api_key = await get_secret(db, "openai.api_key", deps.key_bytes)
        cfg = get_settings()
        if (
            not api_key
            and cfg.classification_provider != "ollama"
            and (message_body(message) or prepared.image)
        ):
            raise PermanentError("OpenAI API key is not configured")
        ctx = StageContext(
            db=db,
            moderator=deps.providers.moderation(api_key or ""),
            model=cfg.ollama_model
            if cfg.classification_provider == "ollama"
            else str(await get_setting(db, "classification.model")),
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
            if cfg.local_safety_mode and (
                prepared.problem is not None or message.type in ("other", "poll")
            ):
                if prepared.problem is None:
                    prepared.problem = PermanentError(
                        "Poll content was not provided by OpenWA; manual review required"
                        if message.type == "poll"
                        else "Unknown message type; no analyzable content"
                    )
                outcome = PipelineOutcome(verdict="review")
            else:
                message.status = "skipped"  # nothing to classify (no text, transcript or image)
                message.verdict = None
                message.skip_reason = (
                    "Unknown message type; no analyzable content"
                    if message.type == "other"
                    else "No analyzable text, transcript or image"
                )
                await _commit_message(db, job)
                return

        if cfg.local_safety_mode:
            # Check every preserved wording separately: edits must not hide earlier harm.
            revisions = list(
                (
                    await db.scalars(
                        select(MessageRevision)
                        .where(MessageRevision.message_id == message.id)
                        .order_by(MessageRevision.id)
                    )
                ).all()
            )
            for revision in revisions:
                snapshot = Message(
                    id=message.id,
                    chat_id=message.chat_id,
                    sent_at=message.sent_at,
                    type="text",
                    text=revision.text,
                    sender_name=message.sender_name,
                )
                if not (revision.text or "").strip():
                    continue
                earlier = await run_pipeline(snapshot, replace(ctx, image_data_url=None))
                for result in earlier.results:
                    result.stage = "revision_" + result.stage
                if _RANK[earlier.verdict] > _RANK[outcome.verdict]:
                    outcome = PipelineOutcome(
                        verdict=earlier.verdict,
                        results=[*outcome.results, *earlier.results],
                        categories=earlier.categories,
                        max_score=earlier.max_score,
                    )
                else:
                    # Keep the deciding result last for alert category/score extraction.
                    outcome.results = [*earlier.results, *outcome.results]
            if prepared.problem is not None and outcome.verdict != "harmful":
                outcome.verdict = "review"

        # Compare only fully prepared text; media and preserved revisions keep their own checks.
        if prepared.problem is None and prepared.image is None:
            outcome = await compare(message, ctx, outcome)
        _persist(db, message, outcome)
        problem = prepared.problem
        if problem is not None and outcome.verdict != "harmful" and not cfg.local_safety_mode:
            # Only the caption was examined: do not present the message as classified.
            message.verdict = None
            message.status = "failed" if isinstance(problem, PermanentError) else "skipped"
            if message.status == "skipped":
                message.skip_reason = str(problem)[:255]
            await _commit_message(db, job)
            if isinstance(problem, PermanentError):
                raise problem  # visible on the Jobs page, retryable once the cause is fixed
            return
        message.review_reason = (
            (
                str(prepared.problem)[:255]
                if prepared.problem is not None
                else "Classifier scores were inconclusive, including available chat context"
            )
            if outcome.verdict == "review"
            else None
        )
        message.verdict = outcome.verdict
        if (
            message.edited_at is not None
            and _RANK.get(prior_verdict or "", -1) > _RANK[outcome.verdict]
        ):
            # Editing a flagged message into something harmless must not clear the flag.
            message.verdict = prior_verdict
        message.status = "done"
        if outcome.results:
            # Every stage counts: a later look can clear what an earlier one flagged.
            high = [c for r in outcome.results for c in r.high_categories]
            low = [c for r in outcome.results for c in r.flagged_categories]
            if needs_redaction(message.type, high, low):
                # Withhold now, in the same commit as the verdict: a message awaiting review (or
                # with alerts off) must not sit in the DB, search index or portal unredacted.
                redact_message(message)
                await wipe_revisions(db, message.id)
                await mark_purge(db, message.id)  # a kept copy of withheld media goes too
                logger.warning(
                    "message {} redacted at classification; content withheld", message.id
                )
        notification = None
        if message.verdict in ("harmful", "review"):
            notification = Job(
                type="prepare_alert",
                payload={"message_id": message.id},
                run_after=datetime.now(UTC) + timedelta(minutes=1),
            )
            db.add(notification)
        await _commit_message(db, job)
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
        # Before the alert is built, so its text can carry the link. Never fails the job. Every
        # stage's flags count (a flag cleared by the second look still means "do not keep").
        await keep_media(
            deps.session_factory,
            message.id,
            sorted(
                {c for r in outcome.results for c in (*r.high_categories, *r.flagged_categories)}
            ),
            deps.key_bytes,
            deps.data_dir,
            str(job.id),
            examined=prepared.problem is None,
        )
        hook = {"harmful": deps.on_harmful, "review": deps.on_review}.get(outcome.verdict)
        if hook is not None:
            try:
                await hook(db, message, outcome)
                if notification is not None:
                    await db.delete(notification)
                    await _commit_message(db, job)
            except LostLeaseError:
                raise
            except Exception:
                # Classification is done and committed: a failing hook must not mark the message
                # failed or re-run the pipeline. Alert delivery has its own retry.
                logger.exception("alert hook failed for message {}", message.id)


async def prepare_alert(job: ClaimedJob, deps: Deps) -> None:
    """Retry alert creation from the committed decision without reclassifying content."""
    async with deps.session_factory() as db:
        message = await db.get(Message, job.payload.get("message_id"))
        if message is None or message.verdict not in ("harmful", "review"):
            return
        if message.verdict == "review" and (await db.get(ReviewDataIssue, message.id)) is not None:
            return
        if message.verdict == "review" and not await get_setting(db, "alerts.alert_on_review"):
            return
        try:
            await create_alert(db, message, await scores_from_classifications(db, message))
        except Exception as exc:
            raise TransientError("Alert creation temporarily failed") from exc
