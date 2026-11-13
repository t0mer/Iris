from datetime import UTC, datetime

from app.config import get_settings
from app.db.models import Chat, Job, LearningExample, Message, ReviewFeedback, User
from app.security.auth import COOKIE_NAME, make_session_token


async def test_confirmed_missing_content_has_separate_queue_without_safety_labels(app_client):
    from sqlalchemy import func, select

    from app.db.models import ReviewDataIssue

    reasons = [
        "OpenWA has no stored media for this message (check its inbound media storage)",
        "message has no media reference",
        "Unknown message type; no analyzable content",
        "Classifier scores were inconclusive, including available chat context",
        "Document attachment requires manual review",
        None,
    ]
    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="unavailable-chat")
        db.add(chat)
        await db.flush()
        rows = [
            Message(
                chat_id=chat.id,
                wa_message_id=str(i),
                type="image",
                sent_at=datetime.now(UTC),
                status="done",
                verdict="review",
                review_reason=reason,
            )
            for i, reason in enumerate(reasons)
        ]
        db.add_all(rows)
        await db.commit()
        recovered = rows[0].id
    assert (await app_client.get("/api/review")).json()["total"] == 3
    missing = (await app_client.get("/api/review?view=missing_data")).json()
    assert missing["total"] == 3
    assert all(
        row["missing_data"] and row["message"]["verdict"] == "review" for row in missing["items"]
    )
    assert (await app_client.get("/api/stats")).json()["review_queue"] == 3
    summary = (await app_client.get("/api/diagnostics/summary")).json()
    assert summary["manual_review"] == summary["unavailable_content"] == 3
    assert summary["unresolved_review"]["total"] == 6
    async with app_client.app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ReviewFeedback)) == 0
        assert await db.scalar(select(func.count()).select_from(ReviewDataIssue)) == 0
        # A later successful fetch but inconclusive model result returns to manual review.
        message = await db.get(Message, recovered)
        message.review_reason = reasons[3]
        await db.commit()
    assert (await app_client.get("/api/review")).json()["total"] == 4
    assert (await app_client.get("/api/review?view=missing_data")).json()["total"] == 2


async def test_summary_separates_work_from_unresolved_review_and_contains_no_content(app_client):
    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="private-chat")
        db.add(chat)
        await db.flush()
        messages = [
            Message(
                chat_id=chat.id,
                wa_message_id=str(index),
                type="text",
                text="private message content",
                sent_at=datetime.now(UTC),
                status="pending" if index == 0 else "done",
                verdict="review",
                review_reason="whisper.cpp HTTP 422"
                if index == 2
                else "secret provider diagnostic",
            )
            for index in range(4)
        ]
        db.add_all(messages)
        await db.flush()
        db.add(ReviewFeedback(message_id=messages[1].id, verdict="safe"))
        db.add(LearningExample(message_id=messages[1].id, verdict="safe", content_hash="abc"))
        db.add(Job(type="process_message", payload={"message_id": messages[3].id}))
        await db.commit()
    response = await app_client.get("/api/diagnostics/summary")
    assert response.status_code == 200
    result = response.json()
    assert result["pending_processing"] == 2
    assert result["unresolved_review"] == {
        "total": 1,
        "by_reason": {"transcription_failed": 1},
        "by_type": {"text": 1},
    }
    assert result["learning"]["human_labels"] == {"safe": 1}
    assert result["learning"]["enabled_examples"] == {"safe": 1}
    assert "private" not in response.text and "secret provider" not in response.text
    app_client.cookies.clear()
    assert (await app_client.get("/api/diagnostics/summary")).status_code == 401


async def test_import_rejects_feedback_bound_to_different_content(app_client):
    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="changed-content")
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id,
            wa_message_id="1",
            type="text",
            text="changed",
            sent_at=datetime.now(UTC),
            status="done",
            verdict="safe",
        )
        db.add(message)
        await db.flush()
        db.add(ReviewFeedback(message_id=message.id, verdict="safe", content_hash="old-hash"))
        await db.commit()
    result = (await app_client.post("/api/learning/examples/import")).json()
    assert result["scanned"] == 1 and result["imported"] == 0


async def test_diagnostics_requires_admin(app_client):
    async with app_client.app.state.session_factory() as db:
        user = await db.get(User, 1)
        user.role = "parent"
        await db.commit()
        app_client.cookies.set(COOKIE_NAME, make_session_token(get_settings(), user))
    assert (await app_client.get("/api/diagnostics/summary")).status_code == 403


async def test_exhausted_media_goes_to_recovery_only_without_inspectable_evidence(app_client):
    from sqlalchemy import select

    from app.db.models import StoredMedia
    from app.legacy_review import quarantine_legacy_unknowns
    from app.review_queue import EXHAUSTED_REVIEW, OPENWA_RECOVERY_ERROR, unavailable_content

    async with app_client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="recovery")
        db.add(chat)
        await db.flush()
        rows = [
            Message(
                chat_id=chat.id,
                wa_message_id=str(i),
                type="image",
                status="failed",
                verdict="review",
                review_reason=EXHAUSTED_REVIEW,
                sent_at=datetime.now(UTC),
            )
            for i in range(5)
        ]
        rows[1].text = "readable caption"
        rows[2].transcript = "readable transcript"
        db.add_all(rows)
        await db.flush()
        for row in rows:
            db.add(
                Job(
                    type="process_message",
                    payload={"message_id": row.id},
                    status="dead",
                    last_error=OPENWA_RECOVERY_ERROR,
                )
            )
        await db.flush()
        db.add(
            Job(
                type="process_message",
                payload={"message_id": rows[4].id},
                status="dead",
                last_error="classifier timeout",
            )
        )
        db.add(
            StoredMedia(
                message_id=rows[3].id,
                backend="local",
                key="synthetic",
                content_type="image/png",
                kind="image",
                size_bytes=50,
                sha256="a" * 64,
            )
        )
        await db.commit()
        await quarantine_legacy_unknowns(db)
        await quarantine_legacy_unknowns(db)
        assert list(await db.scalars(select(Message.id).where(unavailable_content()))) == [
            rows[0].id
        ]
        assert rows[4].review_reason == EXHAUSTED_REVIEW
        assert all(row.verdict == "review" for row in rows)
        assert not list(await db.scalars(select(ReviewFeedback)))
