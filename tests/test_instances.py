import json

import httpx
import pytest
import respx

from app.db.models import Instance

BODY = {
    "kid_name": "Noa",
    "openwa_base_url": "https://wa.example.com/",
    "openwa_instance_id": "sess-1",
    "openwa_api_key": "super-secret-key",
}


async def test_requires_auth(app_client) -> None:  # type: ignore[no-untyped-def]
    app_client.cookies.clear()
    assert (await app_client.get("/api/instances")).status_code == 401


async def test_create_never_returns_api_key_and_stores_it_encrypted(app_client) -> None:  # type: ignore[no-untyped-def]
    r = await app_client.post("/api/instances", json=BODY)
    assert r.status_code == 201
    out = r.json()
    assert out["api_key_set"] is True and "super-secret-key" not in r.text
    assert out["openwa_base_url"] == "https://wa.example.com"
    assert out["webhook_url"].startswith("http://localhost:8080/webhooks/")
    async with app_client.app.state.session_factory() as s:
        inst = await s.get(Instance, out["id"])
        assert (
            inst and inst.openwa_api_key_enc and "super-secret-key" not in inst.openwa_api_key_enc
        )


async def test_patch_keeps_key_when_blank_and_rotate_changes_url(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    r = await app_client.patch(
        f"/api/instances/{out['id']}", json={"kid_name": "Noa K", "openwa_api_key": ""}
    )
    assert r.json()["kid_name"] == "Noa K" and r.json()["api_key_set"] is True
    rot = await app_client.post(f"/api/instances/{out['id']}/rotate-token")
    assert rot.json()["webhook_url"] != out["webhook_url"]
    assert (await app_client.delete(f"/api/instances/{out['id']}")).status_code == 204
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 404


@respx.mock
async def test_register_webhook_success_and_private_address_hint(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.get("https://wa.example.com/api/sessions/sess-1/webhooks").mock(
        return_value=httpx.Response(200, json=[])
    )
    route = respx.post("https://wa.example.com/api/sessions/sess-1/webhooks").mock(
        return_value=httpx.Response(201, json={"id": "wh-1"})
    )
    r = await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    assert r.json() == {"webhook_id": "wh-1"}
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "super-secret-key"
    assert b"/webhooks/" in sent.content and b"secret" in sent.content
    for event in (b"message.edited", b"message.revoked"):
        assert event in sent.content

    route.mock(
        return_value=httpx.Response(400, json={"message": "Destination address is not allowed"})
    )
    r = await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    assert r.status_code == 502 and "OpenWA webhook base URL" in r.json()["detail"]
    persisted = (await app_client.get(f"/api/instances/{out['id']}")).json()
    assert persisted["monitoring_status"] == "failed"
    assert "Destination address is not allowed" in persisted["monitoring_error"]
    route.mock(return_value=httpx.Response(201, json={"id": "wh-1"}))
    assert (
        await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    ).status_code == 200
    persisted = (await app_client.get(f"/api/instances/{out['id']}")).json()
    assert persisted["monitoring_status"] == "registered"
    assert persisted["monitoring_error"] is None


@respx.mock
async def test_register_webhook_updates_the_existing_one(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    base = "https://wa.example.com/api/sessions/sess-1/webhooks"
    other = {"id": "wh-other", "url": "https://elsewhere.example/hook", "events": ["*"]}
    mine = {"id": "wh-1", "url": out["webhook_url"], "events": ["message.received", "group.join"]}
    respx.get(base).mock(return_value=httpx.Response(200, json={"data": [other, mine]}))
    put = respx.put(f"{base}/wh-1").mock(return_value=httpx.Response(200, json={}))
    create = respx.post(base).mock(return_value=httpx.Response(201, json={"id": "new"}))
    r = await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    assert r.json() == {"webhook_id": "wh-1"}
    assert not create.called
    body = json.loads(put.calls.last.request.content)
    assert {"message.edited", "message.revoked", "group.join"} <= set(body["events"])
    assert body["secret"]


@pytest.mark.parametrize("bad", [{"kid_name": ""}, {}])
async def test_create_validation(app_client, bad) -> None:  # type: ignore[no-untyped-def]
    assert (await app_client.post("/api/instances", json=bad)).status_code == 422


async def test_base_url_validation(app_client) -> None:  # type: ignore[no-untyped-def]
    for bad in ("ftp://x", "not a url", "http://169.254.169.254/latest", "http://0.0.0.0"):
        r = await app_client.post("/api/instances", json={**BODY, "openwa_base_url": bad})
        assert r.status_code == 422, bad
    ok = await app_client.post(
        "/api/instances", json={**BODY, "openwa_base_url": "http://192.168.0.5:2785"}
    )
    assert ok.status_code == 201  # private LAN addresses are legitimate OpenWA hosts


async def test_changing_base_url_requires_reentering_key(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    url = f"/api/instances/{out['id']}"
    r = await app_client.patch(url, json={"openwa_base_url": "https://evil.example"})
    assert r.status_code == 422
    r = await app_client.patch(
        url, json={"openwa_base_url": "https://new.example", "openwa_api_key": "k2"}
    )
    assert r.status_code == 200 and r.json()["openwa_base_url"] == "https://new.example"


@respx.mock
async def test_upstream_error_text_not_reflected_and_odd_json_survives(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.get("https://wa.example.com/api/sessions/sess-1/webhooks").mock(
        return_value=httpx.Response(200, json=[])
    )
    route = respx.post("https://wa.example.com/api/sessions/sess-1/webhooks")
    route.mock(return_value=httpx.Response(500, text="SECRET INTERNAL BODY"))
    r = await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    assert r.status_code == 502 and "SECRET" not in r.text
    route.mock(return_value=httpx.Response(500, json=["not", "a", "dict"]))
    assert (
        await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    ).status_code == 502


@respx.mock
async def test_session_id_is_path_quoted(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (
        await app_client.post("/api/instances", json={**BODY, "openwa_instance_id": "../admin"})
    ).json()
    respx.get(url__regex=r"https://wa\.example\.com/api/sessions/.*/webhooks").mock(
        return_value=httpx.Response(200, json=[])
    )
    route = respx.post(url__regex=r"https://wa\.example\.com/api/sessions/.*/webhooks").mock(
        return_value=httpx.Response(201, json={"id": "w"})
    )
    await app_client.post(f"/api/instances/{out['id']}/register-webhook")
    assert route.calls.last.request.url.raw_path.startswith(b"/api/sessions/..%2Fadmin/webhooks")


@respx.mock
async def test_delete_openwa_opt_in_logs_out_then_deletes(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    logout = respx.post("https://wa.example.com/api/sessions/sess-1/logout").mock(
        return_value=httpx.Response(200, json={})
    )
    delete = respx.delete("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(204)
    )
    response = await app_client.delete(f"/api/instances/{out['id']}?delete_openwa=true")
    assert response.status_code == 204
    assert logout.called and delete.called
    assert logout.calls.last.request.headers["x-api-key"] == BODY["openwa_api_key"]
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 404


@respx.mock
async def test_openwa_delete_failure_keeps_iris_phone_for_retry(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.post("https://wa.example.com/api/sessions/sess-1/logout").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.delete("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(503)
    )
    assert (
        await app_client.delete(f"/api/instances/{out['id']}?delete_openwa=true")
    ).status_code == 502
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 200


@respx.mock
async def test_openwa_already_deleted_allows_iris_removal(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.post("https://wa.example.com/api/sessions/sess-1/logout").mock(
        return_value=httpx.Response(404)
    )
    respx.delete("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(404)
    )
    assert (
        await app_client.delete(f"/api/instances/{out['id']}?delete_openwa=true")
    ).status_code == 204


@respx.mock
async def test_verified_create_rejects_wrong_key_without_saving(app_client) -> None:  # type: ignore[no-untyped-def]
    respx.get("https://wa.example.com/api/sessions/sess-1").mock(return_value=httpx.Response(401))
    response = await app_client.post("/api/instances", json={**BODY, "verify_openwa": True})
    assert response.status_code == 502
    assert "API key was rejected" in response.json()["detail"]
    assert (await app_client.get("/api/instances")).json() == []


@respx.mock
async def test_verified_create_reads_openwa_phone(app_client) -> None:  # type: ignore[no-untyped-def]
    respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(200, json={"id": "sess-1", "phone": "15550100101"})
    )
    response = await app_client.post("/api/instances", json={**BODY, "verify_openwa": True})
    assert response.status_code == 201
    assert response.json()["phone_number"] == "15550100101"


@respx.mock
async def test_staged_removal_keeps_iris_until_both_stages_finish(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    logout = respx.post("https://wa.example.com/api/sessions/sess-1/logout").mock(
        return_value=httpx.Response(200, json={})
    )
    delete = respx.delete("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(503)
    )
    path = f"/api/instances/{out['id']}"
    assert (await app_client.post(path + "/remove-openwa?stage=deactivate")).status_code == 204
    assert logout.called and not delete.called
    assert (await app_client.get(path)).status_code == 200
    assert (await app_client.post(path + "/remove-openwa?stage=delete")).status_code == 502
    assert (await app_client.get(path)).status_code == 200
    delete.mock(return_value=httpx.Response(204))
    assert (await app_client.post(path + "/remove-openwa?stage=delete")).status_code == 204
    assert (await app_client.get(path)).status_code == 200
    assert (await app_client.delete(path)).status_code == 204


async def test_edit_session_id_and_iris_label_are_persisted(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    response = await app_client.patch(
        f"/api/instances/{out['id']}",
        json={
            "kid_name": "New name",
            "openwa_instance_id": "new-id",
            "session_name": "Family session",
            "phone_number": "15550100101",
            "enabled": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["session_name"] == "Family session"
    assert response.json()["openwa_instance_id"] == "new-id"
    assert (await app_client.get(f"/api/instances/{out['id']}")).json()[
        "session_name"
    ] == "Family session"


@respx.mock
async def test_invalid_key_edit_keeps_original_connection(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.get("https://wa.example.com/api/sessions/new-id").mock(return_value=httpx.Response(401))
    response = await app_client.patch(
        f"/api/instances/{out['id']}",
        json={"openwa_instance_id": "new-id", "openwa_api_key": "wrong-key", "verify_openwa": True},
    )
    assert response.status_code == 502
    unchanged = (await app_client.get(f"/api/instances/{out['id']}")).json()
    assert unchanged["openwa_instance_id"] == "sess-1"


async def test_deleted_sender_selection_cannot_attach_to_new_child(app_client) -> None:  # type: ignore[no-untyped-def]
    parent = (await app_client.post("/api/instances", json={**BODY, "role": "parent"})).json()
    response = await app_client.put(
        "/api/settings", json={"settings": {"alerts.sender_instance_id": parent["id"]}}
    )
    assert response.status_code == 200
    assert (await app_client.delete(f"/api/instances/{parent['id']}")).status_code == 204
    child = (await app_client.post("/api/instances", json={**BODY, "role": "child"})).json()
    assert child["role"] == "child"
    assert (await app_client.get("/api/settings")).json()["alerts.sender_instance_id"] is None
    assert (await app_client.get("/api/stats")).json()["alert_sender_configured"] is False


async def test_stale_sender_is_cleared_before_creating_child(app_client) -> None:  # type: ignore[no-untyped-def]
    from app.settings_store import set_setting

    async with app_client.app.state.session_factory() as db:
        await set_setting(db, "alerts.sender_instance_id", 1)
    await app_client.post("/api/instances", json={**BODY, "role": "child"})
    assert (await app_client.get("/api/settings")).json()["alerts.sender_instance_id"] is None


@respx.mock
async def test_phone_status_reports_repairing_and_recovery(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    route = respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(200, json={"status": "qr_ready"})
    )
    response = await app_client.post(f"/api/instances/{out['id']}/check-session")
    assert response.status_code == 200
    assert response.json()["connection_status"] == "qr_ready"
    assert response.json()["connection_checked_at"]
    assert response.json()["enabled"] is True
    route.mock(return_value=httpx.Response(200, json={"status": "ready"}))
    assert (await app_client.post(f"/api/instances/{out['id']}/check-session")).json()[
        "connection_status"
    ] == "ready"


@respx.mock
async def test_repair_existing_session_returns_qr_without_removing_phone(app_client) -> None:  # type: ignore[no-untyped-def]
    import base64

    out = (await app_client.post("/api/instances", json=BODY)).json()
    qr = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode()
    respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(200, json={"status": "qr_ready"})
    )
    respx.get("https://wa.example.com/api/sessions/sess-1/qr").mock(
        return_value=httpx.Response(200, json={"qrCode": qr})
    )
    response = await app_client.post(f"/api/instances/{out['id']}/re-pair")
    assert response.status_code == 200 and response.json()["qr"] == qr
    assert response.headers["cache-control"] == "no-store"
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 200


@respx.mock
async def test_repair_disconnected_session_starts_existing_id(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(200, json={"status": "disconnected"})
    )
    start = respx.post("https://wa.example.com/api/sessions/sess-1/start").mock(
        return_value=httpx.Response(200, json={})
    )
    assert (await app_client.post(f"/api/instances/{out['id']}/re-pair")).json()[
        "status"
    ] == "initializing"
    assert start.called


@respx.mock
async def test_embedded_qr_rejects_invalid_and_expires_unchanged_image(app_client) -> None:  # type: ignore[no-untyped-def]
    import base64
    import time

    from app.api.instances import _qr_seen

    _qr_seen.clear()
    out = (await app_client.post("/api/instances", json=BODY)).json()
    qr = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode()
    provider = respx.get("https://wa.example.com/api/sessions/sess-1/qr").mock(
        return_value=httpx.Response(200, json={"qrCode": qr})
    )
    url = f"/api/instances/{out['id']}/qr"
    first = await app_client.get(url)
    assert first.json() == {"status": "qr_ready", "qr": qr}
    assert first.headers["cache-control"] == "no-store"
    assert provider.calls.last.request.headers["x-api-key"] == "super-secret-key"
    digest = _qr_seen[(out["id"], "sess-1")][0]
    _qr_seen[(out["id"], "sess-1")] = (digest, time.monotonic() - 121)
    assert (await app_client.get(url)).json() == {"status": "expired", "qr": None}
    provider.mock(
        return_value=httpx.Response(200, json={"qrCode": "data:image/png;base64,bm90IGFuIGltYWdl"})
    )
    invalid = await app_client.get(url)
    assert invalid.status_code == 502 and "invalid QR" in invalid.json()["detail"]
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 200
    _qr_seen.clear()


@respx.mock
async def test_new_qr_refreshes_only_disconnected_session_and_never_logs_out(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    session = respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )
    stop = respx.post("https://wa.example.com/api/sessions/sess-1/stop").mock(
        return_value=httpx.Response(200, json={})
    )
    start = respx.post("https://wa.example.com/api/sessions/sess-1/start").mock(
        return_value=httpx.Response(200, json={})
    )
    url = f"/api/instances/{out['id']}/qr/refresh"
    assert (await app_client.post(url)).json()["status"] == "ready"
    assert not stop.called and not start.called
    session.mock(return_value=httpx.Response(200, json={"status": "qr_ready"}))
    assert (await app_client.post(url)).json()["status"] == "waiting"
    assert stop.called and start.called
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 200


@respx.mock
async def test_repair_reports_timeout_cause_without_leaking_sender_key(app_client) -> None:  # type: ignore[no-untyped-def]
    out = (await app_client.post("/api/instances", json=BODY)).json()
    respx.get("https://wa.example.com/api/sessions/sess-1").mock(
        side_effect=httpx.ReadTimeout("timeout with private upstream data")
    )
    result = await app_client.post(f"/api/instances/{out['id']}/re-pair")
    assert result.status_code == 502 and "did not respond in time" in result.json()["detail"]
    assert "private upstream" not in result.text and "super-secret" not in result.text
    assert (await app_client.get(f"/api/instances/{out['id']}")).status_code == 200
