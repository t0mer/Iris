from typing import Any

from sqlalchemy import func, select

from app.db.models import Alert, AlertView, MediaWarningDismissal, Message
from tests.test_alert_views import accounts, login
from tests.test_alerts_api import seeded


async def test_warning_dismissal_is_personal_and_does_not_read_alerts(app_client: Any) -> None:
    await seeded(app_client)
    admin, viewer = await accounts(app_client)
    async with app_client.app.state.session_factory() as db:
        messages = list(await db.scalars(select(Message).order_by(Message.id)))
        for m in messages[:2]:
            m.type = "image"
        await db.commit()
    initial = (await app_client.get("/api/stats")).json()
    assert initial["alert_media_warning_count"] == 2
    cutoff = initial["alert_media_warning_latest_id"]
    # A new affected alert appears after this user's displayed warning snapshot.
    async with app_client.app.state.session_factory() as db:
        messages = list(await db.scalars(select(Message).order_by(Message.id)))
        messages[2].type = "image"
        await db.commit()
    for _ in range(2):
        response = await app_client.post(
            "/api/stats/media-warning/dismiss", json={"through_alert_id": cutoff}
        )
        assert response.status_code == 200
    updated = (await app_client.get("/api/stats")).json()
    assert updated["alert_media_not_saved"] == 3
    assert updated["alert_media_warning_count"] == 1
    assert updated["alerts_by_status"] == initial["alerts_by_status"]
    async with app_client.app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AlertView)) == 0
        assert await db.scalar(select(func.count()).select_from(MediaWarningDismissal)) == 2
        assert set(await db.scalars(select(Alert.status))) == {"new"}
    login(app_client, viewer)
    assert (await app_client.get("/api/stats")).json()["alert_media_warning_count"] == 3
    login(app_client, admin)
    latest = updated["alert_media_warning_latest_id"]
    await app_client.post("/api/stats/media-warning/dismiss", json={"through_alert_id": latest})
    assert (await app_client.get("/api/stats")).json()["alert_media_warning_count"] == 0
    assert (await app_client.get("/api/alerts?view=all&media=missing")).json()["total"] == 3
    assert (
        await app_client.post("/api/stats/media-warning/dismiss", json={"through_alert_id": -1})
    ).status_code == 422
    app_client.cookies.clear()
    assert (
        await app_client.post("/api/stats/media-warning/dismiss", json={"through_alert_id": latest})
    ).status_code == 401
