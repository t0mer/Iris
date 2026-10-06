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
    assert r.status_code == 502 and "public hostname" in r.json()["detail"]


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
