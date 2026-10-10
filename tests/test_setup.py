from typing import Any

import respx

from app.config import get_settings
from app.monitoring import states
from tests.test_instances import BODY


async def test_only_admin_accounts_can_access_setup_reminders(app_client: Any) -> None:
    from sqlalchemy import select

    from app.db.models import User
    from app.security.auth import COOKIE_NAME, make_session_token

    async with app_client.app.state.session_factory() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        tokens = []
        for role in ("parent", "watch"):
            user = User(username=f"setup-{role}", role=role, password_hash=admin.password_hash)
            db.add(user)
            await db.flush()
            tokens.append(make_session_token(get_settings(), user))
        await db.commit()
    for token in tokens:
        app_client.cookies.clear()
        app_client.cookies.set(COOKIE_NAME, token)
        assert (await app_client.get("/api/setup")).status_code == 403
        assert (await app_client.get("/api/setup/reminders")).status_code == 403
        assert (await app_client.post("/api/setup/check")).status_code == 403
        assert (await app_client.post("/api/setup/ai/test/ollama")).status_code == 403


async def test_home_reminders_keep_essentials_and_dismiss_only_optional(app_client: Any) -> None:
    await app_client.post("/api/setup/progress", json={"skip": "openwa"})
    await app_client.post(
        "/api/setup/progress", json={"finish": True, "acknowledge_incomplete": True}
    )
    state = (await app_client.get("/api/setup/reminders")).json()
    assert len(state["steps"]) == 6
    assert state["skipped"] == ["openwa"]
    for step in ("openwa", "notifiers", "parents", "children", "ai"):
        response = await app_client.post("/api/setup/reminders/dismiss", json={"step": step})
        assert response.status_code == 422
    response = await app_client.post("/api/setup/reminders/dismiss", json={"step": "defaults"})
    assert response.status_code == 200
    assert len(response.json()["steps"]) == 5
    assert len((await app_client.get("/api/setup/reminders")).json()["steps"]) == 5
    # Dismissing does not claim the defaults were reviewed or complete any configuration.
    status = (await app_client.get("/api/setup")).json()
    assert all(not step["ready"] for step in status["steps"])
    app_client.cookies.clear()
    assert (await app_client.get("/api/setup/reminders")).status_code == 401


async def test_setup_dismissal_is_private_to_each_admin(app_client: Any) -> None:
    from sqlalchemy import select

    from app.db.models import User
    from app.security.auth import COOKIE_NAME, make_session_token

    await app_client.post("/api/setup/reminders/dismiss", json={"step": "defaults"})
    async with app_client.app.state.session_factory() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        other = User(username="other-admin", role="admin", password_hash=admin.password_hash)
        db.add(other)
        await db.commit()
        token = make_session_token(get_settings(), other)
    app_client.cookies.clear()
    app_client.cookies.set(COOKIE_NAME, token)
    assert "defaults" in [
        s["id"] for s in (await app_client.get("/api/setup/reminders")).json()["steps"]
    ]


async def test_fresh_setup_skip_warns_and_finish_requires_acknowledgement(app_client: Any) -> None:
    state = (await app_client.get("/api/setup")).json()
    assert state["needs_setup"]
    assert len(state["steps"]) == 6 and len(state["warnings"]) == 6
    response = await app_client.post("/api/setup/progress", json={"skip": "openwa"})
    assert response.json()["skipped"] == ["openwa"]
    assert not response.json()["steps"][0]["ready"]
    assert (await app_client.post("/api/setup/progress", json={"finish": True})).status_code == 409
    finished = (
        await app_client.post(
            "/api/setup/progress", json={"finish": True, "acknowledge_incomplete": True}
        )
    ).json()
    assert finished["finished"] and not finished["needs_setup"] and finished["warnings"]
    assert (await app_client.get("/api/setup")).json()["finished"]
    app_client.cookies.clear()
    assert (await app_client.get("/api/setup")).status_code == 401


async def test_child_check_probes_actual_session_and_never_counts_sender(
    app_client: Any, monkeypatch: Any
) -> None:
    states.clear()
    iid = (await app_client.post("/api/instances", json=BODY)).json()["id"]

    async def probe(instance: Any, key: bytes) -> None:
        states[instance.id] = True

    monkeypatch.setattr("app.api.setup.probe_instance", probe)
    status = (await app_client.post("/api/setup/check")).json()
    assert status["steps"][0]["ready"] and status["steps"][3]["ready"]
    await app_client.put("/api/settings", json={"settings": {"alerts.sender_instance_id": iid}})
    status = (await app_client.get("/api/setup")).json()
    assert status["steps"][0]["ready"] and not status["steps"][3]["ready"]
    states.clear()


@respx.mock
async def test_environment_openwa_check_only_reads_sessions(
    app_client: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(get_settings(), "openwa_url", "http://openwa.test")
    monkeypatch.setattr(get_settings(), "openwa_api_key", "synthetic")
    route = respx.get("http://openwa.test/api/sessions").respond(
        200, json={"data": [{"status": "ready"}]}
    )
    state = (await app_client.post("/api/setup/check")).json()
    assert route.called and state["steps"][0]["ready"]
    assert not state["steps"][3]["ready"]
    assert all(call.request.method == "GET" for call in respx.calls)
