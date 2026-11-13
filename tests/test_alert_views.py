import asyncio
from typing import Any

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db.models import Alert, AlertView, User
from app.security.auth import COOKIE_NAME, make_session_token
from tests.test_alerts_api import seeded


async def accounts(client: Any) -> tuple[str, str]:
    async with client.app.state.session_factory() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        other = User(username="viewer", role="watch", password_hash=admin.password_hash)
        db.add(other)
        await db.commit()
        return make_session_token(get_settings(), admin), make_session_token(get_settings(), other)


def login(client: Any, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)


async def test_read_state_filters_and_badges_are_per_account(app_client: Any):
    await seeded(app_client)
    admin, viewer = await accounts(app_client)
    assert (await app_client.get("/api/alerts/1")).json()["status"] == "new"
    assert (await app_client.get("/api/alerts")).json()["total"] == 3  # Fetching is not opening.
    marked = await app_client.post("/api/alerts/1/seen", json={"seen": True})
    assert marked.json()["status"] == "acknowledged" and marked.json()["seen_at"]
    assert (await app_client.get("/api/alerts")).json()["total"] == 2
    assert (await app_client.get("/api/alerts?view=seen")).json()["total"] == 1
    assert (await app_client.get("/api/alerts?view=all")).json()["total"] == 3
    assert (await app_client.get("/api/stats")).json()["alerts_by_status"] == {
        "new": 2,
        "acknowledged": 1,
    }
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(Alert, 1)).status == "new"
    login(app_client, viewer)
    assert (await app_client.get("/api/alerts")).json()["total"] == 3
    assert (await app_client.get("/api/stats")).json()["alerts_by_status"] == {"new": 3}
    assert (await app_client.post("/api/alerts/1/seen", json={"seen": True})).status_code == 200
    login(app_client, admin)
    assert (await app_client.post("/api/alerts/1/seen", json={"seen": False})).json()[
        "status"
    ] == "new"
    assert (await app_client.get("/api/alerts")).json()["total"] == 3
    login(app_client, viewer)
    assert (await app_client.get("/api/alerts")).json()["total"] == 2


async def test_repeated_opens_are_idempotent_and_alert_deletion_cascades(app_client: Any):
    await seeded(app_client)
    responses = await asyncio.gather(
        *[app_client.post("/api/alerts/1/seen", json={"seen": True}) for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json()["seen_at"] == responses[1].json()["seen_at"]
    async with app_client.app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AlertView)) == 1
        await db.execute(delete(Alert).where(Alert.id == 1))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(AlertView)) == 0


async def test_dismiss_is_personal_and_read_views_validate(app_client: Any):
    await seeded(app_client)
    _, viewer = await accounts(app_client)
    await app_client.patch("/api/alerts/1", json={"status": "dismissed"})
    assert (await app_client.post("/api/alerts/1/seen", json={"seen": True})).json()[
        "status"
    ] == "dismissed"
    assert (await app_client.get("/api/alerts?view=dismissed")).json()["total"] == 1
    assert (await app_client.get("/api/alerts?view=seen")).json()["total"] == 1
    assert (await app_client.get("/api/alerts?view=invalid")).status_code == 422
    assert (await app_client.get("/api/alerts?status=invalid")).status_code == 422
    login(app_client, viewer)
    assert (await app_client.get("/api/alerts")).json()["total"] == 3
    assert (await app_client.get("/api/alerts?view=dismissed")).json()["total"] == 0
    assert (await app_client.post("/api/alerts/999/seen", json={"seen": True})).status_code == 404
    app_client.cookies.clear()
    assert (await app_client.post("/api/alerts/1/seen", json={"seen": True})).status_code == 401


async def test_page_entry_marks_only_displayed_alerts_for_current_user(app_client: Any):
    await seeded(app_client)
    admin, viewer = await accounts(app_client)
    shown = (await app_client.get("/api/alerts?page_size=2")).json()["items"]
    ids = [a["id"] for a in shown]
    responses = await asyncio.gather(
        *[app_client.post("/api/alerts/seen", json={"alert_ids": ids + ids}) for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in responses)
    assert sum(r.json()["marked"] for r in responses) == 2
    assert (await app_client.get("/api/alerts")).json()["total"] == 1
    assert (await app_client.get("/api/stats")).json()["alerts_by_status"]["new"] == 1
    async with app_client.app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AlertView)) == 2
        assert all(a.status == "new" for a in await db.scalars(select(Alert)))
    login(app_client, viewer)
    assert (await app_client.get("/api/alerts")).json()["total"] == 3
    assert (await app_client.post("/api/alerts/seen", json={"alert_ids": [1]})).status_code == 200
    assert (await app_client.get("/api/alerts")).json()["total"] == 2
    login(app_client, admin)
    await app_client.patch("/api/alerts/1", json={"status": "dismissed"})
    await app_client.post("/api/alerts/seen", json={"alert_ids": [1]})
    assert (await app_client.get("/api/alerts/1")).json()["status"] == "dismissed"
    assert (await app_client.post("/api/alerts/seen", json={"alert_ids": []})).status_code == 422
    assert (
        await app_client.post("/api/alerts/seen", json={"alert_ids": [1] * 101})
    ).status_code == 422
    await app_client.post("/api/alerts/3/seen", json={"seen": False})
    assert (
        await app_client.post("/api/alerts/seen", json={"alert_ids": [3, 999]})
    ).status_code == 404
    assert (await app_client.get("/api/alerts/3")).json()["status"] == "new"
    app_client.cookies.clear()
    assert (await app_client.post("/api/alerts/seen", json={"alert_ids": [1]})).status_code == 401


async def test_missing_media_link_includes_read_alerts_and_matches_home_count(app_client: Any):
    from app.db.models import Message, StoredMedia

    mids = await seeded(app_client)
    async with app_client.app.state.session_factory() as db:
        (await db.get(Message, mids[0])).type = "image"
        (await db.get(Message, mids[1])).type = "voice"
        withheld = await db.get(Message, mids[2])
        withheld.type, withheld.redacted = "image", True
        await db.commit()
    await app_client.post("/api/alerts/seen", json={"alert_ids": [1, 2, 3]})
    assert (await app_client.get("/api/alerts")).json()["total"] == 0

    async def affected():
        page = (await app_client.get("/api/alerts?view=all&media=missing")).json()
        stats = (await app_client.get("/api/stats")).json()
        assert page["total"] == stats["alert_media_not_saved"]
        return page

    assert {a["message_id"] for a in (await affected())["items"]} == set(mids[:2])
    async with app_client.app.state.session_factory() as db:
        copy = StoredMedia(
            message_id=mids[0],
            backend="local",
            key="test-image",
            content_type="image/png",
            kind="image",
            size_bytes=10,
            sha256="a" * 64,
        )
        db.add(copy)
        await db.commit()
        copy_id = copy.id
    assert (await affected())["total"] == 1
    async with app_client.app.state.session_factory() as db:
        (await db.get(StoredMedia, copy_id)).purge = True
        await db.commit()
    assert (await affected())["total"] == 2
    assert (await app_client.get("/api/alerts?media=invalid")).status_code == 422
