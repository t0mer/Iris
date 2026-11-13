from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import Chat, Job, Message, ReviewDataIssue, ReviewFeedback


async def seed(client):
    async with client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="triage")
        db.add(chat)
        await db.flush()
        rows = []
        for index, (kind, reason) in enumerate(
            [
                ("text", "Classifier scores were inconclusive, including available chat context"),
                (
                    "video",
                    "Video exceeds the 30-second local visual analysis limit; "
                    "manual review required",
                ),
                ("image", "ffmpeg failed: decode unavailable"),
                (
                    "image",
                    "OpenWA has no stored media for this message (check its inbound media storage)",
                ),
            ]
        ):
            m = Message(
                chat_id=chat.id,
                wa_message_id=str(index),
                type=kind,
                sent_at=datetime.now(UTC),
                status="done",
                verdict="review",
                review_reason=reason,
                media={"message_ref": str(index)},
            )
            db.add(m)
            rows.append(m)
        await db.commit()
        return [m.id for m in rows]


async def test_reason_filters_count_entire_queue_before_pagination(app_client):
    ids = await seed(app_client)
    result = (await app_client.get("/api/review?page_size=1&reason=technical")).json()
    assert result["total"] == 1
    assert result["reason_counts"] == {"uncertain": 1, "attachment": 1, "technical": 1}
    assert result["items"][0]["message"]["id"] == ids[2]
    assert result["items"][0]["can_recover_media"]
    missing = (await app_client.get("/api/review?view=missing_data")).json()
    assert missing["items"][0]["review_kind"] == "unavailable"
    assert missing["total"] == 1
    assert (await app_client.get("/api/review?reason=invented")).status_code == 422


async def test_unknown_attachment_can_be_recovered_without_safety_override(app_client):
    mid = (await seed(app_client))[1]
    async with app_client.app.state.session_factory() as db:
        m = await db.get(Message, mid)
        m.type = "other"
        m.review_reason = "This attachment format cannot be analyzed yet; manual review required"
        await db.commit()
    result = (await app_client.get("/api/review?reason=attachment")).json()
    item = next(row for row in result["items"] if row["message"]["id"] == mid)
    assert item["can_recover_media"] and item["review_kind"] == "attachment"
    assert (await app_client.post(f"/api/messages/{mid}/recover-media")).status_code == 200
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(Message, mid)).status == "pending"
        assert await db.get(ReviewFeedback, mid) is None


async def test_explicit_recovery_queues_once_and_preserves_missing_data_until_success(app_client):
    mid = (await seed(app_client))[3]
    async with app_client.app.state.session_factory() as db:
        db.add(ReviewDataIssue(message_id=mid, issue="missing_data"))
        await db.commit()
    url = f"/api/messages/{mid}/recover-media"
    assert (await app_client.post(url)).status_code == 200
    assert (await app_client.post(url)).status_code == 409
    async with app_client.app.state.session_factory() as db:
        job = await db.scalar(select(Job))
        assert job.payload == {"message_id": mid, "media_recovery": True}
        assert await db.get(ReviewDataIssue, mid)
        assert await db.get(ReviewFeedback, mid) is None
        job.status = "dead"
        m = await db.get(Message, mid)
        m.status = "failed"
        await db.commit()
    assert (await app_client.post(url)).status_code == 429


@pytest.mark.parametrize("state", ["revoked", "redacted", "no_reference", "text"])
async def test_recovery_rejects_unrecoverable_content(app_client, state):
    mid = (await seed(app_client))[3]
    async with app_client.app.state.session_factory() as db:
        m = await db.get(Message, mid)
        if state == "revoked":
            m.revoked_at = datetime.now(UTC)
        elif state == "redacted":
            m.redacted = True
        elif state == "text":
            m.type = "text"
        else:
            m.media = None
        await db.commit()
    assert (await app_client.post(f"/api/messages/{mid}/recover-media")).status_code == 409
    if state in {"revoked", "redacted"}:
        assert (await app_client.post(f"/api/messages/{mid}/reprocess")).status_code == 409
    app_client.cookies.clear()
    assert (await app_client.post(f"/api/messages/{mid}/recover-media")).status_code == 401
