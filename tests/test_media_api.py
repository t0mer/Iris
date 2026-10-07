from typing import Any

import respx
from sqlalchemy import update

from app.db.models import Message, StoredMedia
from tests.test_media_keep import _keep_one, files, moderate, policy, rows
from tests.test_media_pipeline import MEDIA, run_all, serve, setup
from tests.test_webhooks import fx, post

ORIGINAL = (MEDIA / "image.png").read_bytes()


@respx.mock
async def test_the_file_is_served_to_the_owner_with_safe_headers(app_client: Any) -> None:
    row = await _keep_one(app_client)
    r = await app_client.get(f"/api/media/{row.id}")
    assert r.status_code == 200 and r.content == ORIGINAL
    assert r.headers["content-type"] == "image/png"
    assert r.headers["content-disposition"] == "inline"
    assert r.headers["cache-control"] == "private, no-store"
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["accept-ranges"] == "bytes" and int(r.headers["content-length"]) == len(
        ORIGINAL
    )


@respx.mock
async def test_it_needs_a_login(app_client: Any) -> None:
    row = await _keep_one(app_client)
    app_client.cookies.clear()
    assert (await app_client.get(f"/api/media/{row.id}")).status_code == 401
    assert (await app_client.get(f"/api/media/{row.id}/info")).status_code == 401


@respx.mock
async def test_byte_ranges_work_for_players(app_client: Any) -> None:
    row = await _keep_one(app_client)
    r = await app_client.get(f"/api/media/{row.id}", headers={"Range": "bytes=2-9"})
    assert r.status_code == 206 and r.content == ORIGINAL[2:10]
    assert r.headers["content-range"] == f"bytes 2-9/{len(ORIGINAL)}"
    tail = await app_client.get(f"/api/media/{row.id}", headers={"Range": "bytes=-5"})
    assert tail.status_code == 206 and tail.content == ORIGINAL[-5:]
    open_ended = await app_client.get(f"/api/media/{row.id}", headers={"Range": "bytes=10-"})
    assert open_ended.content == ORIGINAL[10:]
    for bad in ("bytes=999999-", "bytes=9-2", "items=1-2", "bytes=-"):
        r = await app_client.get(f"/api/media/{row.id}", headers={"Range": bad})
        assert r.status_code == 416, bad


@respx.mock
async def test_only_playable_types_are_inline(app_client: Any) -> None:
    row = await _keep_one(app_client)
    async with app_client.app.state.session_factory() as s:
        await s.execute(
            update(StoredMedia).where(StoredMedia.id == row.id).values(content_type="audio/amr")
        )
        await s.commit()
    r = await app_client.get(f"/api/media/{row.id}")
    assert r.headers["content-disposition"].startswith("attachment;")


@respx.mock
async def test_scheduled_or_withheld_or_orphaned_media_is_not_shown(app_client: Any) -> None:
    row = await _keep_one(app_client)
    async with app_client.app.state.session_factory() as s:
        await s.execute(update(StoredMedia).where(StoredMedia.id == row.id).values(purge=True))
        await s.commit()
    assert (await app_client.get(f"/api/media/{row.id}")).status_code == 404
    assert (await app_client.get(f"/api/media/{row.id}/info")).status_code == 404
    async with app_client.app.state.session_factory() as s:
        await s.execute(update(StoredMedia).where(StoredMedia.id == row.id).values(purge=False))
        await s.execute(update(Message).values(redacted=True))  # withheld after the fact
        await s.commit()
    assert (await app_client.get(f"/api/media/{row.id}")).status_code == 404
    assert (await app_client.get("/api/media/9999")).status_code == 404


@respx.mock
async def test_a_missing_file_ends_the_stream_instead_of_a_server_error(app_client: Any) -> None:
    row = await _keep_one(app_client)
    for f in files():
        f.unlink()
    r = await app_client.get(f"/api/media/{row.id}")
    assert r.status_code == 200 and r.content == b""


@respx.mock
async def test_info_links_the_file_to_its_message_and_alert(app_client: Any) -> None:
    deps, token = await setup(app_client)
    await policy(app_client, "harmful")
    serve("image.png", "image/png")
    moderate(violence=0.9)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    (row,) = await rows(app_client)
    info = (await app_client.get(f"/api/media/{row.id}/info")).json()
    alert = (await app_client.get("/api/alerts")).json()["items"][0]
    assert info == {
        "id": row.id,
        "kind": "image",
        "content_type": "image/png",
        "size_bytes": len(ORIGINAL),
        "inline": True,
        "message_id": row.message_id,
        "alert_id": alert["id"],
    }
    assert alert["media"]["id"] == row.id and alert["media"]["kind"] == "image"
    assert (await app_client.get(f"/api/alerts/{alert['id']}")).json()["media"]["id"] == row.id
    assert (await app_client.get(f"/api/messages/{row.message_id}")).json()["media"]["id"] == row.id


@respx.mock
async def test_alerts_without_kept_media_say_so(app_client: Any) -> None:
    deps, token = await setup(app_client)
    serve("image.png", "image/png")
    moderate(violence=0.9)
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    alert = (await app_client.get("/api/alerts")).json()["items"][0]
    assert alert["media"] is None


@respx.mock
async def test_stats_count_what_is_kept(app_client: Any) -> None:
    s = (await app_client.get("/api/stats")).json()
    assert (s["media_policy"], s["media_files"], s["media_bytes"]) == ("off", 0, 0)
    await _keep_one(app_client)
    s = (await app_client.get("/api/stats")).json()
    assert (s["media_policy"], s["media_files"], s["media_bytes"]) == ("all", 1, len(ORIGINAL))


@respx.mock
async def test_the_whatsapp_alert_carries_the_media_link(app_client: Any) -> None:
    import json

    import httpx

    from tests.test_alerts import SEND_URL
    from tests.test_alerts import setup as alert_setup

    deps, token, _ = await alert_setup(app_client)
    await policy(app_client, "harmful")
    serve("image.png", "image/png")
    moderate(violence=0.9)
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    (row,) = await rows(app_client)
    text = json.loads(send.calls.last.request.content)["text"]
    assert f"/media/{row.id}" in text and "📎 Media kept (image," in text
    assert text.index("📎") < text.index("Open:")


@respx.mock
async def test_a_withheld_message_alert_has_no_media_line(app_client: Any) -> None:
    import json

    import httpx

    from tests.test_alerts import SEND_URL
    from tests.test_alerts import setup as alert_setup

    deps, token, _ = await alert_setup(app_client)
    await policy(app_client, "all")
    serve("image.png", "image/png")
    moderate(**{"sexual/minors": 0.9})
    send = respx.post(SEND_URL).mock(return_value=httpx.Response(201, json={}))
    await post(app_client, token, fx("image_nocaption_received"))
    await run_all(deps)
    text = json.loads(send.calls.last.request.content)["text"]
    assert "Media kept" not in text and "withheld" in text
