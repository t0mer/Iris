from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.classify.moderation import URL as MOD_URL
from app.config import get_settings
from app.db.models import Message, StoredMedia
from app.media.sniff import kind_of, sniff
from app.media.sweep import sweep_media
from app.transcription import openai as openai_t
from tests.test_media_pipeline import MEDIA, no_tmp_left, run_all, serve, setup
from tests.test_webhooks import fx, post
from tests.test_worker import mod_response

SAFE, REVIEW, HARMFUL = {}, {"violence": 0.3}, {"violence": 0.9}


async def policy(c: Any, value: str, **more: Any) -> None:
    r = await c.put("/api/settings", json={"settings": {"media.policy": value, **more}})
    assert r.status_code == 200, r.text


async def rows(c: Any) -> list[StoredMedia]:
    async with c.app.state.session_factory() as s:
        return list((await s.execute(select(StoredMedia).order_by(StoredMedia.id))).scalars())


def files() -> list[Path]:
    root = get_settings().data_dir / "media"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def moderate(**scores: float) -> None:
    respx.post(MOD_URL).mock(return_value=mod_response(**scores))


# --- sniffing ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"\xff\xd8\xff\xe0" + b"x" * 12, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * 8, "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio/wav"),
        (b"OggS\x00\x02" + b"x" * 10, "audio/ogg"),
        (b"\x00\x00\x00\x18ftypM4A ", "audio/mp4"),
        (b"\x00\x00\x00\x18ftypisom", "video/mp4"),
        (b"\x1a\x45\xdf\xa3" + b"x" * 12, "video/webm"),
        (b"ID3\x04" + b"x" * 12, "audio/mpeg"),
    ],
)
def test_real_formats_are_recognised_by_their_bytes(head: bytes, expected: str) -> None:
    found = sniff(head)
    assert found and found[0] == expected


@pytest.mark.parametrize(
    "head",
    [
        b"<!DOCTYPE html><html>",
        b"<svg xmlns=",
        b"<script>alert(1)",
        b"#EXTM3U\n#EXT",
        b"PK\x03\x04",
        b"",
    ],
)
def test_pages_scripts_and_archives_are_never_kept(head: bytes) -> None:
    assert sniff(head) is None


def test_only_checkable_message_types_have_a_kind() -> None:
    assert [kind_of(t) for t in ("image", "sticker", "voice", "audio")] == [
        "image", "image", "audio", "audio",
    ]  # fmt: skip
    # Videos are never kept: Iris checks what they say, not what they show.
    assert kind_of("video") is None and kind_of("text") is None and kind_of("document") is None


# --- policy -----------------------------------------------------------------------------------


@respx.mock
async def test_nothing_is_kept_by_default(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("image.png", "image/png")
    moderate(**HARMFUL)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert await rows(app_client) == [] and files() == []
    assert no_tmp_left(app_client)


@respx.mock
@pytest.mark.parametrize(
    ("pol", "scores", "kept"),
    [
        ("harmful", HARMFUL, True),
        ("harmful", REVIEW, False),
        ("harmful", SAFE, False),
        ("harmful_review", HARMFUL, True),
        ("harmful_review", REVIEW, True),
        ("harmful_review", SAFE, False),
        ("all", HARMFUL, True),
        ("all", REVIEW, True),
        ("all", SAFE, True),
    ],
)
async def test_the_policy_decides_by_verdict(
    app_client: Any, pol: str, scores: dict[str, float], kept: bool
) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, pol)
    serve("image.png", "image/png")
    respx.post(MOD_URL).mock(return_value=mod_response(**scores))
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert bool(await rows(app_client)) is kept and bool(files()) is kept


@respx.mock
async def test_a_kept_image_is_the_original_with_its_real_type(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    (row,) = await rows(app_client)
    original = (MEDIA / "image.png").read_bytes()
    assert (row.kind, row.content_type, row.backend, row.purge) == (
        "image",
        "image/png",
        "local",
        False,
    )
    assert (
        row.size_bytes == len(original)
        and row.key == f"media/{row.message_id}/{row.sha256[:16]}.png"
    )
    assert files()[0].read_bytes() == original  # not the JPEG made for moderation
    assert no_tmp_left(app_client)


@respx.mock
async def test_a_voice_note_is_kept_as_audio(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("voice.ogg", "audio/ogg")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "שלום"}))
    moderate()
    await post(app_client, token, fx("voice_sent"))
    await run_all(deps)
    (row,) = await rows(app_client)
    assert (row.kind, row.content_type) == ("audio", "audio/ogg")


@respx.mock
@pytest.mark.parametrize("pol", ["harmful", "all"])
async def test_a_video_is_never_kept(app_client: Any, pol: str) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, pol)
    serve("video_audio.mp4", "video/mp4")
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "hello"}))
    moderate(**HARMFUL)  # even a video with a threatening line: its pictures were never checked
    await post(app_client, token, fx("video_sent"))
    await run_all(deps)
    assert await rows(app_client) == [] and files() == []


@respx.mock
async def test_media_that_could_not_be_checked_is_not_kept(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.queue import PermanentError
    from app.media import ffmpeg

    async def broken(src: Any, dest: Any) -> None:
        raise PermanentError("unsupported media format")

    monkeypatch.setattr(ffmpeg, "image_to_jpeg", broken)
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("anim.gif", "image/gif")
    moderate(**HARMFUL)  # the caption alone is harmful; the picture was never examined
    await post(app_client, token, fx("image_caption_sent"))
    await run_all(deps)
    assert (await _the_message(app_client)).verdict == "harmful"
    assert await rows(app_client) == [] and files() == []


@respx.mock
async def test_the_file_must_match_the_kind_of_message(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")  # a "voice note" that is really a picture
    respx.post(openai_t.URL).mock(return_value=httpx.Response(200, json={"text": "hi"}))
    moderate()
    await post(app_client, token, fx("voice_sent"))
    await run_all(deps)
    assert await rows(app_client) == []


# --- the safety rule --------------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize("pol", ["harmful", "harmful_review", "all"])
async def test_withheld_media_is_never_kept_whatever_the_policy(app_client: Any, pol: str) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, pol)
    serve("image.png", "image/png")
    moderate(**{"sexual/minors": 0.9})
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    m = await _the_message(app_client)
    assert m.redacted and await rows(app_client) == [] and files() == []


@respx.mock
async def test_sexual_imagery_is_never_kept(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate(sexual=0.95)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert (await _the_message(app_client)).redacted
    assert await rows(app_client) == [] and files() == []


@respx.mock
async def test_a_later_check_that_withholds_the_message_removes_the_copy(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert len(files()) == 1
    respx.post(MOD_URL).mock(return_value=mod_response(**{"sexual/minors": 0.9}))
    mid = (await _the_message(app_client)).id
    assert (await app_client.post(f"/api/messages/{mid}/reprocess")).status_code == 200
    await run_all(deps)
    (row,) = await rows(app_client)
    assert row.purge is True  # hidden at once...
    assert (await app_client.get(f"/api/media/{row.id}")).status_code == 404
    await sweep_media(
        app_client.app.state.session_factory, get_settings().key_bytes, get_settings().data_dir
    )
    assert await rows(app_client) == [] and files() == []  # ...and deleted by the sweeper


async def _the_message(c: Any) -> Message:
    async with c.app.state.session_factory() as s:
        return (await s.execute(select(Message))).scalar_one()


# --- robustness -------------------------------------------------------------------------------


@respx.mock
async def test_checking_again_keeps_one_copy(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    mid = (await _the_message(app_client)).id
    await app_client.post(f"/api/messages/{mid}/reprocess")
    await run_all(deps)
    assert len(await rows(app_client)) == 1 and len(files()) == 1


@respx.mock
async def test_an_unkeepable_file_is_skipped_without_failing_the_check(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    respx.get(url__regex=r"https://wa\.x/api/sessions/s/messages/.*/media").mock(
        return_value=httpx.Response(200, content=b"<html><script>x</script></html>")
    )
    moderate()
    await post(app_client, token, fx("document_sent"))  # a document: not downloaded at all
    await run_all(deps)
    assert await rows(app_client) == [] and files() == []


@respx.mock
async def test_a_storage_outage_never_fails_classification(app_client: Any, no_dns: None) -> None:
    deps, token = await setup(app_client)
    await policy(
        app_client,
        "all",
        **{
            "media.backend": "s3",
            "media.s3_endpoint": "https://s3.example.com",
            "media.s3_bucket": "iris-media",
            "media.s3_access_key": "k",
            "media.s3_secret_key": "s",
        },
    )
    serve("image.png", "image/png")
    respx.route(host="s3.example.com").mock(side_effect=httpx.ConnectError("down"))
    moderate(**HARMFUL)
    await post(app_client, token, fx("image_nocaption_received"))
    assert (await run_all(deps))[0] == "done"  # classification itself was not affected
    assert (await _the_message(app_client)).verdict == "harmful"
    assert await rows(app_client) == []


@respx.mock
async def test_incomplete_storage_settings_are_a_logged_failure_not_a_crash(
    app_client: Any,
) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "all", **{"media.backend": "s3"})
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    assert await run_all(deps) == ["done"]
    assert await rows(app_client) == []


# --- review findings ---------------------------------------------------------------------------


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The S3 hosts in these tests do not exist: skip the per-request address check."""
    from app.media import s3

    async def fine(endpoint: str) -> None:
        return None

    monkeypatch.setattr(s3, "refuse_blocked_resolution", fine)


@respx.mock
async def test_a_database_error_while_keeping_never_loses_the_alert(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from app.db.models import Alert
    from app.media import keep

    async def locked(*a: Any, **k: Any) -> None:
        raise OperationalError("COMMIT", {}, Exception("database is locked"))

    monkeypatch.setattr(keep, "_store", locked)
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate(**HARMFUL)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(Alert))).scalar_one() == 1
    assert await rows(app_client) == []


@respx.mock
async def test_a_withholding_that_lands_mid_download_flags_the_new_copy(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.media import keep

    real = keep.fetch_original

    async def fetch_then_withhold(db: Any, message: Any, key_bytes: bytes, dest: Path) -> str:
        ctype = await real(db, message, key_bytes, dest)
        async with app_client.app.state.session_factory() as s:  # the owner resolves it meanwhile
            await s.execute(update(Message).values(redacted=True))
            await s.commit()
        return ctype

    monkeypatch.setattr(keep, "fetch_original", fetch_then_withhold)
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    (row,) = await rows(app_client)
    assert row.purge is True  # never servable...
    await sweep_media(
        app_client.app.state.session_factory, get_settings().key_bytes, get_settings().data_dir
    )
    assert await rows(app_client) == [] and files() == []  # ...and gone at the next sweep


@respx.mock
async def test_flags_from_any_stage_stop_the_copy(app_client: Any) -> None:
    from app.media.keep import keep_media

    deps, token = await setup(app_client)
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)  # policy off: nothing kept yet
    await policy(app_client, "all")
    mid = (await _the_message(app_client)).id
    args = (app_client.app.state.session_factory, mid)
    tail = (get_settings().key_bytes, get_settings().data_dir, "t")
    assert await keep_media(*args, ["sexual/minors"], *tail) is None  # flagged by the first look
    assert await rows(app_client) == []
    assert await keep_media(*args, [], *tail) is not None


@respx.mock
async def test_an_upload_that_could_not_be_recorded_leaves_no_object(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import AsyncSession

    real_commit = AsyncSession.commit

    async def failing(self: Any) -> None:
        if any(isinstance(o, StoredMedia) for o in self.new):
            raise OperationalError("COMMIT", {}, Exception("disk I/O error"))
        await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", failing)
    deps, token = await setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate()
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert await rows(app_client) == [] and files() == []


@respx.mock
async def test_a_file_stays_findable_after_the_storage_settings_change(
    app_client: Any, no_dns: None
) -> None:
    import json

    row = await _keep_one(app_client)
    loc = json.dumps(
        {
            "endpoint": "https://old-s3.example.com",
            "bucket": "old-bucket",
            "prefix": "iris/",
            "region": "auto",
            "path_style": True,
        }
    )
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(StoredMedia)
            .where(StoredMedia.id == row.id)
            .values(backend="s3", location=loc, purge=True)
        )
        await s.commit()
    await app_client.put(  # the owner has since moved to another bucket
        "/api/settings",
        json={
            "settings": {
                "media.backend": "s3",
                "media.s3_endpoint": "https://new-s3.example.com",
                "media.s3_bucket": "new-bucket",
                "media.s3_access_key": "k",
                "media.s3_secret_key": "s",
            }
        },
    )
    old = respx.route(host="old-s3.example.com").mock(return_value=httpx.Response(204))
    new = respx.route(host="new-s3.example.com").mock(return_value=httpx.Response(204))
    assert await _sweep(app_client) == 1
    assert old.call_count == 1 and not new.called
    assert "/old-bucket/iris/" in str(old.calls.last.request.url)


@respx.mock
async def test_stuck_rows_do_not_starve_the_others(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.media import sweep

    monkeypatch.setattr(sweep, "BATCH", 2)
    row = await _keep_one(app_client)
    async with app_client.app.state.session_factory() as s:
        for i in range(3):  # three S3 rows that can never be deleted (nothing configured)
            s.add(
                StoredMedia(
                    message_id=row.message_id,
                    backend="s3",
                    key=f"media/9/x{i}.png",
                    content_type="image/png",
                    kind="image",
                    size_bytes=1,
                    sha256=f"{i:064d}",
                    purge=True,
                )
            )
        await s.execute(update(StoredMedia).where(StoredMedia.id == row.id).values(purge=True))
        await s.commit()
    for _ in range(3):
        await _sweep(app_client)
    left = await rows(app_client)
    assert row.id not in [r.id for r in left] and files() == []  # the deletable one went
    assert len(left) == 3 and all(r.purge_attempts >= 1 for r in left)


@respx.mock
async def test_deleting_all_kept_media_hides_it_at_once(app_client: Any) -> None:
    row = await _keep_one(app_client)
    r = await app_client.delete("/api/media")
    assert r.json() == {"scheduled": 1}
    assert (await app_client.get(f"/api/media/{row.id}")).status_code == 404
    assert await _sweep(app_client) == 1 and files() == []


# --- the sweeper ------------------------------------------------------------------------------


async def _keep_one(c: Any) -> StoredMedia:
    deps, token = await setup(c)
    await policy(c, "all")
    serve("image.png", "image/png")
    moderate()
    await post(c, token, fx("image_nocaption_received"))
    await run_all(deps)
    (row,) = await rows(c)
    return row


async def _sweep(c: Any) -> int:
    return await sweep_media(
        c.app.state.session_factory, get_settings().key_bytes, get_settings().data_dir
    )


@respx.mock
async def test_media_expires_after_its_own_retention(app_client: Any) -> None:
    row = await _keep_one(app_client)
    assert await _sweep(app_client) == 0 and len(files()) == 1  # fresh
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(StoredMedia)
            .where(StoredMedia.id == row.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=31))
        )
        await s.commit()
    assert await _sweep(app_client) == 1
    assert await rows(app_client) == [] and files() == []
    async with app_client.app.state.session_factory() as s:  # the message itself stays
        assert (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 1


@respx.mock
async def test_a_longer_retention_setting_keeps_it(app_client: Any) -> None:
    row = await _keep_one(app_client)
    await app_client.put("/api/settings", json={"settings": {"media.retention_days": 90}})
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(StoredMedia)
            .where(StoredMedia.id == row.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=60))
        )
        await s.commit()
    assert await _sweep(app_client) == 0 and len(files()) == 1


@respx.mock
async def test_deleting_the_message_removes_its_media_afterwards(app_client: Any) -> None:
    await _keep_one(app_client)
    async with app_client.app.state.session_factory() as s:
        (await s.execute(select(Message))).scalar_one()
        from sqlalchemy import delete

        await s.execute(delete(Message))
        await s.commit()
    assert len(files()) == 1  # the row outlived the message, so nothing is orphaned
    assert await _sweep(app_client) == 1 and files() == []


@respx.mock
async def test_an_unreachable_bucket_keeps_the_row_flagged_for_the_next_sweep(
    app_client: Any, no_dns: None
) -> None:
    row = await _keep_one(app_client)
    async with app_client.app.state.session_factory() as s:  # pretend it lives in an S3 bucket
        await s.execute(
            update(StoredMedia).where(StoredMedia.id == row.id).values(backend="s3", purge=True)
        )
        await s.commit()
    await app_client.put(
        "/api/settings",
        json={
            "settings": {
                "media.s3_endpoint": "https://s3.example.com",
                "media.s3_bucket": "iris-media",
                "media.s3_access_key": "k",
                "media.s3_secret_key": "s",
            }
        },
    )
    s3 = respx.route(host="s3.example.com").mock(side_effect=httpx.ConnectError("down"))
    assert await _sweep(app_client) == 0
    (left,) = await rows(app_client)
    assert left.purge is True
    s3.mock(return_value=httpx.Response(204))
    assert await _sweep(app_client) == 1 and await rows(app_client) == []


# --- manual review ----------------------------------------------------------------------------


@respx.mock
async def test_marking_a_reviewed_message_harmful_keeps_its_media_under_the_harmful_policy(
    app_client: Any,
) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "harmful")
    serve("image.png", "image/png")
    moderate(**REVIEW)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert await rows(app_client) == []  # a review item is not kept under "harmful only"
    mid = (await _the_message(app_client)).id
    r = await app_client.post(f"/api/review/{mid}", json={"resolution": "harmful"})
    assert r.status_code == 200
    assert len(await rows(app_client)) == 1 and len(files()) == 1


@respx.mock
async def test_marking_a_reviewed_message_safe_drops_media_kept_only_for_review(
    app_client: Any,
) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "harmful_review")
    serve("image.png", "image/png")
    moderate(**REVIEW)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    assert len(await rows(app_client)) == 1
    mid = (await _the_message(app_client)).id
    await app_client.post(f"/api/review/{mid}", json={"resolution": "safe"})
    (row,) = await rows(app_client)
    assert row.purge is True
    await _sweep(app_client)
    assert files() == []
