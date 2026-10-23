from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Chat,
    Classification,
    Job,
    LearningExample,
    Message,
    ReviewDataIssue,
    ReviewFeedback,
    ReviewResponse,
    User,
)


async def seed(client, kind="text", text="A harmless greeting", **kwargs):
    async with client.app.state.session_factory() as db:
        chat = Chat(wa_chat_id="bot-test")
        db.add(chat)
        await db.flush()
        message = Message(
            chat_id=chat.id,
            wa_message_id="bot-test",
            type=kind,
            text=text,
            status="done",
            verdict="review",
            sent_at=datetime.now(UTC),
            **kwargs,
        )
        db.add(message)
        await db.commit()
        return message.id


async def authorize(client):
    response = await client.post("/api/bot/token")
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["token"]


async def test_scoped_token_explicit_rotation_and_revocation(app_client):
    assert (await app_client.get("/api/bot/reviews")).status_code == 401
    await authorize(app_client)
    headers = dict(app_client.headers)
    assert (await app_client.get("/api/bot/reviews")).status_code == 200
    await authorize(app_client)
    assert (await app_client.get("/api/bot/reviews", headers=headers)).status_code == 401
    assert (await app_client.delete("/api/bot/token")).status_code == 200
    assert (await app_client.get("/api/bot/reviews")).status_code == 401
    await authorize(app_client)
    app_client.cookies.clear()
    assert (await app_client.get("/api/bot/reviews")).status_code == 200
    for path in ("/api/settings", "/api/messages", "/api/docs"):
        assert (await app_client.get(path)).status_code == 401
    assert (await app_client.post("/api/bot/token")).status_code == 401


@pytest.mark.parametrize("change", ["password", "role", "expired"])
async def test_token_is_bound_to_current_admin_and_expiry(app_client, monkeypatch, change):
    await authorize(app_client)
    if change == "expired":
        from itsdangerous.timed import TimestampSigner

        from app.api.bot_review import TOKEN_AGE

        future = TimestampSigner("test").get_timestamp() + TOKEN_AGE + 1
        monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: future)
    else:
        async with app_client.app.state.session_factory() as db:
            user = await db.scalar(select(User).where(User.role == "admin"))
            if change == "password":
                user.password_hash = "changed"
            else:
                user.role = "parent"
            await db.commit()
    assert (await app_client.get("/api/bot/reviews")).status_code == 401


async def test_bot_safe_is_audited_but_never_human_feedback(app_client):
    mid = await seed(app_client)
    await authorize(app_client)
    data = (await app_client.get(f"/api/bot/reviews/{mid}")).json()
    assert data["text"] == "A harmless greeting" and data["safe_allowed"]
    body = {"action": "safe", "revision": data["revision"], "reason": "Ordinary greeting"}
    response = await app_client.post(f"/api/bot/reviews/{mid}", json=body)
    assert response.status_code == 200
    assert response.json()["training_label_created"] is False
    assert (await app_client.post(f"/api/bot/reviews/{mid}", json=body)).status_code == 409
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(Message, mid)).verdict == "safe"
        assert await db.get(ReviewFeedback, mid) is None
        assert await db.get(LearningExample, mid) is None
        assert await db.scalar(select(func.count()).select_from(ReviewResponse)) == 1
        assert (await db.scalar(select(Classification))).stage == "bot_review"
    # A parent may correct a bot decision; only that later action is human feedback.
    response = await app_client.post(f"/api/review/{mid}", json={"resolution": "ignored"})
    assert response.status_code == 200
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(ReviewFeedback, mid)).verdict == "ignored"
        m = await db.get(Message, mid)
        m.redacted = True
        await db.commit()
        response = await db.scalar(
            select(ReviewResponse).where(ReviewResponse.actor.startswith("MCP bot: "))
        )
        assert response.note == "Bot review: content withheld"


@pytest.mark.parametrize("change", ["edit", "human", "pending", "redacted", "revoked"])
async def test_stale_or_human_decisions_are_not_overwritten(app_client, change):
    mid = await seed(app_client)
    await authorize(app_client)
    data = (await app_client.get(f"/api/bot/reviews/{mid}")).json()
    async with app_client.app.state.session_factory() as db:
        m = await db.get(Message, mid)
        if change == "edit":
            m.text = "Changed content"
        elif change == "human":
            db.add(ReviewFeedback(message_id=mid, verdict="harmful"))
        elif change == "pending":
            db.add(Job(type="process_message", payload={"message_id": mid}))
        elif change == "redacted":
            m.redacted = True
        else:
            m.revoked_at = datetime.now(UTC)
        await db.commit()
    response = await app_client.post(
        f"/api/bot/reviews/{mid}",
        json={
            "action": "safe",
            "revision": data["revision"],
            "reason": "Read earlier",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "kind,text,extra",
    [
        ("image", "Harmless caption", {}),
        ("text", "", {}),
        ("text", "x" * 16001, {}),
        ("text", "Hidden", {"redacted": True}),
        ("text", "Deleted", {"revoked_at": datetime.now(UTC)}),
    ],
)
async def test_missing_visuals_truncation_and_withheld_content_cannot_be_safe(
    app_client,
    kind,
    text,
    extra,
):
    mid = await seed(app_client, kind, text, **extra)
    await authorize(app_client)
    data = (await app_client.get(f"/api/bot/reviews/{mid}")).json()
    assert not data["safe_allowed"]
    if extra:
        assert data["text"] == "" and data["context"] == []
    result = await app_client.post(
        f"/api/bot/reviews/{mid}",
        json={
            "action": "safe",
            "revision": data["revision"],
            "reason": "Incomplete evidence",
        },
    )
    assert result.status_code == 409


@pytest.mark.parametrize("action", ["harmful", "ignored", "review", "missing_data"])
async def test_other_outcomes_preserve_provenance(app_client, action):
    mid = await seed(app_client)
    await authorize(app_client)
    data = (await app_client.get(f"/api/bot/reviews/{mid}")).json()
    result = await app_client.post(
        f"/api/bot/reviews/{mid}",
        json={
            "action": action,
            "revision": data["revision"],
            "reason": "Synthetic test evidence",
            "categories": ["harassment"] if action == "harmful" else [],
        },
    )
    assert result.status_code == 200, result.text
    async with app_client.app.state.session_factory() as db:
        assert await db.get(ReviewFeedback, mid) is None
        assert await db.get(LearningExample, mid) is None
        assert (await db.get(Message, mid)).verdict == (
            "review" if action in {"review", "missing_data"} else action
        )
        if action == "missing_data":
            assert await db.get(ReviewDataIssue, mid)
    if action == "missing_data":
        assert not (await app_client.get("/api/bot/reviews")).json()["items"]
        assert (await app_client.get("/api/bot/reviews?view=unavailable")).json()["items"]


@pytest.mark.parametrize("hidden", ["revoked", "redacted"])
async def test_hidden_content_leaves_actionable_queues_without_training_labels(app_client, hidden):
    extra = {"revoked_at": datetime.now(UTC)} if hidden == "revoked" else {"redacted": True}
    mid = await seed(app_client, "video", "Unavailable attachment", **extra)
    await authorize(app_client)
    assert (await app_client.get("/api/bot/reviews")).json()["items"] == []
    unavailable = (await app_client.get("/api/bot/reviews?view=unavailable")).json()["items"]
    assert [row["id"] for row in unavailable] == [mid]
    detail = (await app_client.get(f"/api/bot/reviews/{mid}")).json()
    assert detail["unavailable"] and not detail["safe_allowed"]
    assert detail["text"] == "" and detail["context"] == []
    assert (await app_client.get("/api/review")).json()["total"] == 0
    assert (await app_client.get("/api/review?view=missing_data")).json()["total"] == 1
    assert (await app_client.get("/api/stats")).json()["review_queue"] == 0
    summary = (await app_client.get("/api/diagnostics/summary")).json()
    assert summary["manual_review"] == 0 and summary["unavailable_content"] == 1
    async with app_client.app.state.session_factory() as db:
        assert (await db.get(Message, mid)).verdict == "review"
        assert await db.get(ReviewFeedback, mid) is None
        assert await db.get(LearningExample, mid) is None
        assert await db.scalar(select(func.count()).select_from(ReviewResponse)) == 0
