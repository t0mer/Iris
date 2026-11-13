import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import respx
from sqlalchemy import select

from app.classify.moderation import ModerationResult
from app.classify.ollama import OllamaModerator
from app.classify.stages import StageContext, _moderate, build_input
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.db.models import Classification, Message
from app.jobs.queue import PermanentError
from app.media import ffmpeg
from tests.test_local_safety import enable
from tests.test_media_pipeline import MEDIA, no_tmp_left, serve, setup
from tests.test_webhooks import fx, post
from tests.test_worker import drain


async def test_one_minute_samples_cover_whole_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(ffmpeg, "probe", AsyncMock(return_value=ffmpeg.MediaInfo(60, False, True)))

    async def decode(*args):
        await asyncio.to_thread(Path(args[-1]).write_bytes, b"jpeg")

    monkeypatch.setattr(ffmpeg, "_run", decode)
    _, frames, times = await ffmpeg.video_frames(tmp_path / "clip.mp4", tmp_path)
    assert len(frames) == 12
    assert times[0] == 0 and times[-1] == 59.9
    assert max(b - a for a, b in zip(times, times[1:], strict=False)) < 5.5


@pytest.mark.parametrize("late_result", ["safe", "harmful", "error", "model_changed"])
async def test_video_batches_require_all_evidence_and_keep_highest_risk(late_result):
    first = ModerationResult({"violence": 0.1}, False, {"violence": False})
    second = (
        PermanentError("second visual request failed")
        if late_result == "error"
        else ModerationResult(
            {"violence": 0.9 if late_result == "harmful" else 0.0},
            late_result == "harmful",
            {"violence": late_result == "harmful"},
        )
    )
    moderator = AsyncMock()
    if late_result == "model_changed":
        second.model = "replacement-model"
    moderator.moderate.side_effect = [first, second]
    ctx = StageContext(
        db=None,
        moderator=moderator,
        model="vision",
        thresholds=DEFAULT_THRESHOLDS,
        context_window_size=0,
        context_max_age=timedelta(),
        media_analysis={"method": "sampled_video_v2", "complete": True},
    )
    kind, payload = build_input("complete caption and speech", [str(i) for i in range(12)])
    if late_result in ("error", "model_changed"):
        with pytest.raises(PermanentError):
            await _moderate("moderation", kind, payload, ctx)
    else:
        result = await _moderate("moderation", kind, payload, ctx)
        assert result.band == late_result
        assert result.scores["violence"] == (0.9 if late_result == "harmful" else 0.1)
        assert result.scores["_meta"]["media_analysis"]["visual_batches"] == 2
    calls = moderator.moderate.await_args_list
    assert len(calls) == 2
    assert all(len(call.args[1]) == 7 for call in calls)
    assert all("complete caption and speech" in call.args[1][0]["text"] for call in calls)
    assert [part["image_url"]["url"] for call in calls for part in call.args[1][1:]] == [
        str(i) for i in range(12)
    ]


async def test_video_samples_include_start_and_end_and_are_bounded(tmp_path):
    info, frames, times = await ffmpeg.video_frames(MEDIA / "video_silent.mp4", tmp_path)
    assert info.has_video and not info.has_audio
    assert times[0] == 0 and times[-1] == pytest.approx(info.duration - 0.1)
    assert 1 <= len(frames) <= ffmpeg.MAX_VIDEO_FRAMES
    assert all(p.read_bytes().startswith(b"\xff\xd8\xff") for p in frames)


@pytest.mark.parametrize("duration", [None, float("nan"), float("inf"), 0, 61])
async def test_unsupported_duration_never_decodes_a_misleading_prefix(
    tmp_path, monkeypatch, duration
):
    monkeypatch.setattr(
        ffmpeg, "probe", AsyncMock(return_value=ffmpeg.MediaInfo(duration, True, True))
    )
    decoder = AsyncMock()
    monkeypatch.setattr(ffmpeg, "_run", decoder)
    with pytest.raises(PermanentError):
        await ffmpeg.video_frames(MEDIA / "video_audio.mp4", tmp_path)
    decoder.assert_not_awaited()


async def test_missing_sample_does_not_clear_video(tmp_path, monkeypatch):
    # A retry after a worker crash must not reuse a frame from the old attempt.
    (tmp_path / "video-frame-0.jpg").write_bytes(b"old image")
    monkeypatch.setattr(ffmpeg, "_run", AsyncMock(return_value=(b"", b"")))
    monkeypatch.setattr(ffmpeg, "probe", AsyncMock(return_value=ffmpeg.MediaInfo(2, False, True)))
    with pytest.raises(PermanentError, match="sample could not be decoded"):
        await ffmpeg.video_frames(MEDIA / "video_silent.mp4", tmp_path)


@pytest.mark.parametrize(
    "audio,broken_audio,score,expected",
    [
        (False, False, 0, "safe"),
        (True, False, 0, "safe"),
        (True, True, 0, "review"),
        (True, True, 0.9, "harmful"),
        (False, False, 0.9, "harmful"),
    ],
)
@pytest.mark.parametrize("frame_count", [2, 12])
@respx.mock
async def test_local_video_checks_visuals_and_audio(
    app_client, monkeypatch, audio, broken_audio, score, expected, frame_count
):
    from app.jobs import handlers

    enable(monkeypatch, local=True)
    deps, token = await setup(app_client)
    serve("video_audio.mp4" if audio else "video_silent.mp4", "video/mp4")
    calls = []
    original_frames = ffmpeg.video_frames

    async def sample(src, directory):
        info, frames, times = await original_frames(src, directory)
        if frame_count == 12:
            return ffmpeg.MediaInfo(60, info.has_audio, True), frames * 6, list(range(12))
        return info, frames, times

    monkeypatch.setattr(ffmpeg, "video_frames", sample)

    async def transcribe(db, deps, tmp, message, job=None, *, original=None):
        assert audio and original.is_file()
        if broken_audio:
            raise PermanentError("Speech unavailable")
        message.transcript = "harmless speech"

    async def moderate(self, model, payload):
        images = [part for part in payload if part["type"] == "image_url"]
        assert len(images) == min(frame_count, 6)
        assert all(
            part["image_url"]["url"].startswith("data:image/jpeg;base64,") for part in images
        )
        if audio and not broken_audio:
            assert "harmless speech" in payload[0]["text"]
        calls.append(payload)
        return ModerationResult({"violence": score}, score > 0, {})

    monkeypatch.setattr(handlers, "_transcribe", transcribe)
    monkeypatch.setattr(OllamaModerator, "moderate", moderate)
    await post(app_client, token, fx("video_sent"))
    assert await drain(deps) == ["done"]
    async with deps.session_factory() as db:
        message = (await db.scalars(select(Message))).one()
        assert message.verdict == expected
        rows = list(await db.scalars(select(Classification)))
        assert calls and rows[0].input_kind == "video_frames"
        analysis = rows[0].scores["_meta"]["media_analysis"]
        assert analysis["method"] == "sampled_video_v2"
        assert analysis["audio_checked"] is (not broken_audio)
        assert len(analysis["frame_timestamps"]) == frame_count
        assert analysis["visual_batches"] == (2 if frame_count == 12 else 1)
    assert no_tmp_left(app_client)
    await deps.providers.aclose()


@respx.mock
async def test_unchecked_long_video_still_classifies_its_speech(app_client, monkeypatch):
    from app.jobs import handlers

    enable(monkeypatch, local=True)
    deps, token = await setup(app_client)
    serve("video_audio.mp4", "video/mp4")
    monkeypatch.setattr(
        ffmpeg,
        "video_frames",
        AsyncMock(side_effect=PermanentError("Video exceeds analysis limit")),
    )

    async def transcribe(db, deps, tmp, message, job=None, *, original=None):
        message.transcript = "synthetic harmful speech"

    async def moderate(self, model, payload):
        assert "synthetic harmful speech" in payload
        return ModerationResult({"violence": 0.9}, True, {})

    monkeypatch.setattr(handlers, "_transcribe", transcribe)
    monkeypatch.setattr(OllamaModerator, "moderate", moderate)
    await post(app_client, token, fx("video_sent"))
    assert await drain(deps) == ["done"]
    async with deps.session_factory() as db:
        assert (await db.scalars(select(Message))).one().verdict == "harmful"
    await deps.providers.aclose()
