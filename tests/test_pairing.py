import asyncio
import base64
import time
from typing import Any

import httpx
import respx
from sqlalchemy import select

from app.api import pairing
from app.config import get_settings
from app.db.models import Setting

URL = "https://wa.example"
BODY = {"openwa_base_url": URL, "openwa_api_key": "pairing-secret-key"}
FORM = {
    "kid_name": "Example child",
    "role": "child",
    "openwa_base_url": URL,
    "openwa_instance_id": "draft-id",
    "openwa_api_key": "ignored",
}
QR1 = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nexample-one").decode()
QR2 = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nexample-two").decode()


def routes() -> dict[str, Any]:
    name: dict[str, str] = {}

    def create(request: httpx.Request) -> httpx.Response:
        import json

        name["name"] = json.loads(request.content)["name"]
        return httpx.Response(201, json={"id": "draft-id", **name})

    create_route = respx.post(URL + "/api/sessions").mock(side_effect=create)
    start = respx.post(URL + "/api/sessions/draft-id/start").mock(
        return_value=httpx.Response(200, json={})
    )
    stop = respx.post(URL + "/api/sessions/draft-id/stop").mock(
        return_value=httpx.Response(200, json={})
    )
    status_value = {"status": "qr_ready"}
    status = respx.get(URL + "/api/sessions/draft-id").mock(
        side_effect=lambda _: httpx.Response(200, json={"id": "draft-id", **name, **status_value})
    )
    qr = respx.get(URL + "/api/sessions/draft-id/qr").mock(
        return_value=httpx.Response(200, json={"qrCode": QR1})
    )
    logout = respx.post(URL + "/api/sessions/draft-id/logout").mock(
        return_value=httpx.Response(200, json={})
    )
    delete = respx.delete(URL + "/api/sessions/draft-id").mock(return_value=httpx.Response(204))
    return dict(
        create=create_route,
        start=start,
        stop=stop,
        status=status,
        state=status_value,
        qr=qr,
        logout=logout,
        delete=delete,
    )


@respx.mock
async def test_pair_before_form_complete_rotates_qr_and_cancel_logs_out(app_client: Any) -> None:
    mocked = routes()
    out = await app_client.post("/api/pairing", json=BODY)
    assert out.status_code == 201 and out.json()["qr"] is None
    assert "pairing-secret-key" not in out.text
    token = out.json()["token"]
    assert (await app_client.get("/api/instances")).json() == []
    response = await app_client.get("/api/pairing/" + token)
    assert response.json()["qr"] == QR1 and response.headers["cache-control"] == "no-store"
    mocked["qr"].mock(return_value=httpx.Response(200, json={"qrCode": QR2}))
    assert (await app_client.get("/api/pairing/" + token)).json()["qr"] == QR2
    assert (await app_client.post(f"/api/pairing/{token}/complete", json=FORM)).status_code == 409
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 204
    assert mocked["logout"].call_count == mocked["delete"].call_count == 1
    assert (await app_client.get("/api/pairing/" + token)).status_code == 404


@respx.mock
async def test_invalid_qr_or_connection_error_returns_no_image(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["qr"].mock(
        return_value=httpx.Response(200, json={"qrCode": "https://unsafe.example/image"})
    )
    response = await app_client.get("/api/pairing/" + token)
    assert response.status_code == 200 and response.json()["qr"] is None
    assert mocked["stop"].called and mocked["start"].call_count == 2
    mocked["status"].mock(return_value=httpx.Response(503))
    response = await app_client.get("/api/pairing/" + token)
    assert response.status_code == 502 and "qr" not in response.json()


@respx.mock
async def test_stale_or_manually_refreshed_qr_restarts_only_unpaired_draft(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    assert (await app_client.get("/api/pairing/" + token)).json()["qr"] == QR1
    async with app_client.app.state.session_factory() as db:
        row = await db.get(Setting, pairing.PREFIX + token)
        data = pairing._decode(row, get_settings())
        data["qr_since"] = time.time() - pairing.QR_SECONDS - 1
        await pairing._save(db, row, data, get_settings())
    response = await app_client.get("/api/pairing/" + token)
    assert response.json()["qr"] is None and mocked["stop"].call_count == 1
    await app_client.post(f"/api/pairing/{token}/refresh")
    assert mocked["stop"].call_count == 2
    mocked["state"]["status"] = "ready"
    assert (await app_client.post(f"/api/pairing/{token}/refresh")).json()["status"] == "ready"
    assert mocked["stop"].call_count == 2


@respx.mock
async def test_complete_requires_valid_form_and_transfers_ownership_atomically(
    app_client: Any,
) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["state"]["status"] = "ready"
    assert (
        await app_client.post(f"/api/pairing/{token}/complete", json={**FORM, "role": "invalid"})
    ).status_code == 422
    respx.get(URL + "/api/sessions/draft-id/webhooks").mock(
        return_value=httpx.Response(200, json=[])
    )
    hook = respx.post(URL + "/api/sessions/draft-id/webhooks").mock(
        return_value=httpx.Response(201, json={"id": "hook"})
    )
    response = await app_client.post(f"/api/pairing/{token}/complete", json=FORM)
    assert response.status_code == 201 and response.json()["enabled"] and hook.called
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 204
    assert not mocked["delete"].called  # late close cannot remove the saved session
    assert len((await app_client.get("/api/instances")).json()) == 1


@respx.mock
async def test_ready_but_abandoned_draft_is_cleaned_after_lease(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["state"]["status"] = "ready"
    async with app_client.app.state.session_factory() as db:
        row = await db.get(Setting, pairing.PREFIX + token)
        assert "pairing-secret-key" not in str(row.value)
        data = pairing._decode(row, get_settings())
        data["expires"] = 0
        await pairing._save(db, row, data, get_settings())
    task = asyncio.create_task(pairing.cleanup_loop(app_client.app.state.session_factory))
    try:
        for _ in range(50):
            if mocked["delete"].called:
                break
            await asyncio.sleep(0.02)
        assert mocked["logout"].called and mocked["delete"].called
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@respx.mock
async def test_cancel_failure_is_durable_and_retried(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["delete"].mock(return_value=httpx.Response(503))
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 503
    async with app_client.app.state.session_factory() as db:
        row = await db.get(Setting, pairing.PREFIX + token)
        assert pairing._decode(row, get_settings())["expires"] == 0
    mocked["delete"].mock(return_value=httpx.Response(204))
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 204


@respx.mock
async def test_wrong_session_name_is_not_deleted(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["status"].mock(
        return_value=httpx.Response(200, json={"name": "existing-session", "status": "ready"})
    )
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 409
    assert not mocked["logout"].called and not mocked["delete"].called


@respx.mock
async def test_rejected_api_key_does_not_leave_a_draft_or_qr(app_client: Any) -> None:
    respx.post(URL + "/api/sessions").mock(return_value=httpx.Response(403))
    response = await app_client.post("/api/pairing", json=BODY)
    assert response.status_code == 502 and "qr" not in response.json()
    async with app_client.app.state.session_factory() as db:
        assert (
            await db.scalars(select(Setting).where(Setting.key.startswith(pairing.PREFIX)))
        ).all() == []


@respx.mock
async def test_pairing_parent_does_not_register_monitoring_webhook(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["state"]["status"] = "ready"
    response = await app_client.post(
        f"/api/pairing/{token}/complete", json={**FORM, "role": "parent"}
    )
    assert response.status_code == 201
    assert response.json()["role"] == "parent" and response.json()["enabled"] is False
    assert not mocked["delete"].called


@respx.mock
async def test_other_user_cannot_read_or_cancel_pairing(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    async with app_client.app.state.session_factory() as db:
        row = await db.get(Setting, pairing.PREFIX + token)
        data = pairing._decode(row, get_settings())
        data["owner"] = 999
        await pairing._save(db, row, data, get_settings())
    assert (await app_client.get("/api/pairing/" + token)).status_code == 404
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 404
    assert not mocked["delete"].called


@respx.mock
async def test_failed_webhook_registration_does_not_save_phone(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    mocked["state"]["status"] = "ready"
    respx.get(URL + "/api/sessions/draft-id/webhooks").mock(return_value=httpx.Response(503))
    response = await app_client.post(f"/api/pairing/{token}/complete", json=FORM)
    assert response.status_code == 502
    assert (await app_client.get("/api/instances")).json() == []
    assert (await app_client.delete("/api/pairing/" + token)).status_code == 204
    assert mocked["logout"].called and mocked["delete"].called


@respx.mock
async def test_server_configuration_name_and_phone_number(
    app_client: Any, monkeypatch: Any
) -> None:
    cfg = get_settings()
    monkeypatch.setattr(cfg, "openwa_url", URL)
    monkeypatch.setattr(cfg, "openwa_api_key", "server-secret")
    assert (await app_client.get("/api/pairing/config")).json() == {"configured": True}
    mocked = routes()
    response = await app_client.post("/api/pairing", json={"name": "Example parent"})
    assert response.status_code == 201
    import json

    created = json.loads(mocked["create"].calls.last.request.content)
    assert created["name"].startswith("Example-parent-")
    assert "server-secret" not in response.text
    mocked["state"].update(status="ready", phone="15550100101")
    token = response.json()["token"]
    out = await app_client.post(
        f"/api/pairing/{token}/complete",
        json={**FORM, "role": "parent", "phone_number": "15559999999"},
    )
    assert out.status_code == 201
    assert out.json()["phone_number"] == "15550100101"


async def test_automatic_configuration_missing_key(app_client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(get_settings(), "openwa_url", URL)
    monkeypatch.setattr(get_settings(), "openwa_api_key", None)
    assert (await app_client.get("/api/pairing/config")).json() == {"configured": False}
    assert (await app_client.post("/api/pairing", json={"name": "Example"})).status_code == 409


@respx.mock
async def test_name_optional_after_pairing_defaults_to_session(app_client: Any) -> None:
    mocked = routes()
    draft = (await app_client.post("/api/pairing", json=BODY)).json()
    mocked["state"].update(status="ready", phone="15550100101")
    result = await app_client.post(
        f"/api/pairing/{draft['token']}/complete", json={"role": "parent"}
    )
    assert result.status_code == 201
    assert result.json()["kid_name"] == draft["session_name"]
    assert result.json()["phone_number"] == "15550100101"


@respx.mock
async def test_new_openwa_qr_replaces_old_code_without_restart(app_client: Any) -> None:
    mocked = routes()
    token = (await app_client.post("/api/pairing", json=BODY)).json()["token"]
    await app_client.get("/api/pairing/" + token)
    async with app_client.app.state.session_factory() as db:
        row = await db.get(Setting, pairing.PREFIX + token)
        data = pairing._decode(row, get_settings())
        data["qr_since"] = time.time() - pairing.QR_SECONDS - 1
        await pairing._save(db, row, data, get_settings())
    mocked["qr"].mock(return_value=httpx.Response(200, json={"qrCode": QR2}))
    assert (await app_client.get("/api/pairing/" + token)).json()["qr"] == QR2
    assert not mocked["stop"].called
    assert mocked["start"].call_count == 1


async def test_cleanup_retries_after_database_failure(app_client: Any) -> None:
    import pytest

    calls = 0
    sleeps = 0
    real_sleep = asyncio.sleep
    factory = app_client.app.state.session_factory

    def flaky_factory() -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary database outage")
        return factory()

    async def sleep(seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await pairing.cleanup_loop(flaky_factory, sleep=sleep)
    assert asyncio.sleep is real_sleep
    assert sleeps == 2
    assert calls >= 2  # configuration and durable run history use additional sessions
    from app.db.models import ScheduleRun

    async with factory() as db:
        runs = list(
            await db.scalars(
                select(ScheduleRun).where(ScheduleRun.schedule_key == "pairing_cleanup")
            )
        )
        assert any(run.status == "success" for run in runs)
