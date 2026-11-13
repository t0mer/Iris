"""Security boundary and delivery regression tests (no external mail sent)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx
from sqlalchemy import update

from app.api import auth
from app.db.models import LoginChallenge, Setting, User
from app.security.two_factor import smtp_message
from tests.test_instances import BODY

SMTP = {
    "host": "smtp.gmail.com",
    "port": 587,
    "tls": "starttls",
    "username": "admin@gmail.com",
    "password": "secret-app-password",
    "sender": "admin@gmail.com",
}


async def test_unchanged_user_save_preserves_challenge_binding(app_client: Any) -> None:
    async with app_client.app.state.session_factory() as db:
        user = await db.get(User, 1)
        assert user
        version = user.auth_version
        body = {
            "username": user.username,
            "role": user.role,
            "email": user.email,
            "whatsapp_number": user.whatsapp_number,
        }
    assert (await app_client.put("/api/users/1", json=body)).status_code == 200
    async with app_client.app.state.session_factory() as db:
        user = await db.get(User, 1)
        assert user and user.auth_version == version


def test_pasted_code_normalizes_spaces_and_direction_marks() -> None:
    body = auth.VerifyBody(challenge_id="test", code="\u200e1 2 3 4 5 6\u200f")
    assert body.code == "123456"


async def configure(client: Any, monkeypatch: pytest.MonkeyPatch) -> Mock:
    auth.limiter = auth.LoginLimiter()
    monkeypatch.setattr("app.api.users.reserve_green", AsyncMock())
    monkeypatch.setattr("app.security.two_factor.reserve_green", AsyncMock())

    async def sender_identity(config: dict, **kwargs: Any) -> str:
        config["sender_number"] = "+972501234567"
        return config["sender_number"]

    monkeypatch.setattr("app.api.users.green_sender_number", sender_identity)
    phone_id = (
        await client.post("/api/instances", json={**BODY, "phone_number": "972501234567"})
    ).json()["id"]
    assert (
        await client.put(
            "/api/users/1",
            json={
                "username": "admin",
                "role": "admin",
                "email": "admin@gmail.com",
                "whatsapp_number": "+972509876543",
            },
        )
    ).status_code == 200
    assert (
        await client.put(
            "/api/settings", json={"settings": {"alerts.sender_instance_id": phone_id}}
        )
    ).status_code == 200
    monkeypatch.setattr("app.api.users.send_green_code", AsyncMock())
    assert (
        await client.put(
            "/api/users/security/whatsapp",
            json={"instance_id": "123456", "token": "test-green-token"},
        )
    ).status_code == 200
    sender = Mock()
    monkeypatch.setattr("app.api.users.send_smtp", sender)
    assert (await client.put("/api/users/security/smtp", json=SMTP)).status_code == 200
    return sender


async def enable(client: Any) -> None:
    assert (await client.post("/api/users/security/smtp/test")).json()["ok"]
    assert (await client.post("/api/users/security/whatsapp/test")).json()["ok"]
    # OTP regression tests assume enrolled contacts; approval links have separate tests below.
    async with client.app.state.session_factory() as db:
        await db.execute(
            update(User).where(User.id == 1).values(email_verified=True, whatsapp_verified=True)
        )
        await db.commit()

    assert (
        await client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 200


async def test_six_completed_safety_mode_logins_do_not_lock_out(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    await configure(app_client, monkeypatch)
    await enable(app_client)
    monkeypatch.setattr(get_settings(), "local_safety_mode", True)
    codes: list[str] = []

    async def deliver(*args: Any) -> None:
        codes.append(args[-1])

    monkeypatch.setattr(auth, "deliver", deliver)
    for _ in range(6):
        app_client.cookies.clear()
        login = await app_client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
        )
        assert login.status_code == 200
        verify = await app_client.post(
            "/api/auth/verify",
            json={"challenge_id": login.json()["challenge_id"], "code": codes[-1]},
        )
        assert verify.status_code == 200


async def test_watch_api_boundary(app_client: Any) -> None:
    assert (
        await app_client.post(
            "/api/users", json={"username": "viewer", "password": "watch-password"}
        )
    ).status_code == 201
    app_client.cookies.clear()
    assert (
        await app_client.post(
            "/api/auth/login", json={"username": "viewer", "password": "watch-password"}
        )
    ).status_code == 200
    for path in ("/api/settings", "/api/instances", "/api/jobs", "/api/users", "/api/database"):
        response = await app_client.get(path)
        assert response.status_code in (403, 404), (path, response.text)
    for path in (
        "/api/stats",
        "/api/alerts",
        "/api/review",
        "/api/messages",
        "/api/chats",
        "/api/auth/phones",
    ):
        assert (await app_client.get(path)).status_code == 200
    assert (
        await app_client.put("/api/settings", json={"settings": {"scope.monitor_groups": False}})
    ).status_code == 403
    assert (await app_client.post("/api/classify/test", json={"text": "hello"})).status_code == 403


async def test_two_factor_prerequisites_and_encrypted_smtp(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sender = await configure(app_client, monkeypatch)
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 422
    sender.side_effect = RuntimeError("secret-app-password")
    failed = await app_client.post("/api/users/security/smtp/test")
    assert failed.json()["ok"] is False and "secret-app-password" not in failed.text
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 422
    sender.side_effect = None
    await enable(app_client)
    assert (
        await app_client.put("/api/users/security/smtp", json={**SMTP, "port": 465, "tls": "ssl"})
    ).status_code == 409
    assert (
        await app_client.post(
            "/api/users", json={"username": "no-contact", "password": "some-password"}
        )
    ).status_code == 422
    # Monitoring/alert sender sessions no longer own a user's 2FA recipient.
    assert (await app_client.delete("/api/instances/1")).status_code == 204
    users = (await app_client.get("/api/users")).json()
    assert users[0]["whatsapp_number"] == "+972509876543"
    async with app_client.app.state.session_factory() as db:
        stored = await db.get(Setting, "security.smtp")
        assert stored and "secret-app-password" not in str(stored.value)
    assert "secret-app-password" not in (await app_client.get("/api/users/security/config")).text


async def test_missing_user_contacts_prevent_enable(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    assert (
        await app_client.post(
            "/api/users", json={"username": "no-contact", "password": "some-password"}
        )
    ).status_code == 201
    await app_client.post("/api/users/security/smtp/test")
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 422
    assert (await app_client.get("/api/auth/options")).json()["two_factor_enabled"] is False


async def test_code_required_single_use_and_hashed(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    old_cookie = app_client.cookies.get("iris_session")
    await enable(app_client)
    app_client.cookies.clear()
    app_client.cookies.set("iris_session", old_cookie)
    assert (await app_client.get("/api/auth/me")).status_code == 401
    app_client.cookies.clear()
    captured: list[str] = []

    async def delivery(*args: Any) -> None:
        captured.append(args[-1])

    monkeypatch.setattr(auth, "deliver", delivery)
    r = await app_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
    )
    assert r.json()["two_factor_required"] and "set-cookie" not in r.headers
    assert (await app_client.get("/api/auth/me")).status_code == 401
    challenge = r.json()["challenge_id"]
    async with app_client.app.state.session_factory() as db:
        row = await db.get(LoginChallenge, challenge)
        assert row and row.code_hash != captured[0]
    wrong = "000000" if captured[0] != "000000" else "111111"
    assert (
        await app_client.post("/api/auth/verify", json={"challenge_id": challenge, "code": wrong})
    ).status_code == 401
    body = {"challenge_id": challenge, "code": captured[0]}
    assert (await app_client.post("/api/auth/verify", json=body)).status_code == 200
    assert (await app_client.get("/api/auth/me")).status_code == 200
    assert (await app_client.post("/api/auth/verify", json=body)).status_code == 401


async def test_expired_code_and_changed_user_rejected(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    await enable(app_client)
    captured: list[str] = []

    async def delivery(*args: Any) -> None:
        captured.append(args[-1])

    monkeypatch.setattr(auth, "deliver", delivery)
    app_client.cookies.clear()
    for change in ("expiry", "user"):
        auth.limiter = auth.LoginLimiter()
        r = await app_client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
        )
        challenge = r.json()["challenge_id"]
        async with app_client.app.state.session_factory() as db:
            if change == "expiry":
                await db.execute(
                    update(LoginChallenge)
                    .where(LoginChallenge.id == challenge)
                    .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
                )
            else:
                user = await db.get(User, 1)
                assert user
                user.auth_version += 1
            await db.commit()
        assert (
            await app_client.post(
                "/api/auth/verify", json={"challenge_id": challenge, "code": captured[-1]}
            )
        ).status_code == 401


async def test_concurrent_code_replay(app_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    await configure(app_client, monkeypatch)
    await enable(app_client)

    async def delivery(*args: Any) -> None:
        pass

    monkeypatch.setattr(auth, "deliver", delivery)
    app_client.cookies.clear()
    monkeypatch.setattr("app.api.auth.secrets.randbelow", lambda _: 123456)
    r = await app_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
    )
    body = {"challenge_id": r.json()["challenge_id"], "code": "123456"}
    responses = await asyncio.gather(
        *(app_client.post("/api/auth/verify", json=body) for _ in range(2))
    )
    assert sorted(r.status_code for r in responses) == [200, 401]


async def test_email_format_for_gmail() -> None:
    message = smtp_message(SMTP, "user@gmail.com", "012345")
    assert "verification code" in str(message["Subject"])
    assert message.get_content_type() == "multipart/alternative"
    assert "012345" in message.get_body(preferencelist=("plain",)).get_content()
    assert "012345" in message.get_body(preferencelist=("html",)).get_content()


async def test_whatsapp_code_goes_to_personal_number_via_greenapi(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    await enable(app_client)
    send = AsyncMock()
    monkeypatch.setattr("app.security.two_factor.send_green_code", send)
    app_client.cookies.clear()
    response = await app_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct-horse", "channel": "whatsapp"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["two_factor_required"]
    send.assert_awaited_once()
    args = send.call_args.args
    assert args[0]["instance_id"] == "123456"
    assert args[1] == "+972509876543"


@pytest.mark.parametrize("number", ["0501234567", "+0012345678", "123@c.us", "+972abc"])
async def test_personal_whatsapp_requires_international_number(
    app_client: Any, number: str
) -> None:
    response = await app_client.post(
        "/api/users",
        json={
            "username": "invalid-number",
            "password": "watch-password",
            "whatsapp_number": number,
        },
    )
    assert response.status_code == 422


@respx.mock
async def test_greenapi_copy_button_and_token_redaction(caplog: pytest.LogCaptureFixture) -> None:
    from app.security.two_factor import send_green_code

    caplog.set_level(logging.INFO, logger="httpx")
    config = {
        "api_url": "https://api.green-api.com",
        "instance_id": "123456",
        "token": "never-log-this-token",
    }
    respx.get(
        "https://api.green-api.com/waInstance123456/getStateInstance/never-log-this-token"
    ).mock(return_value=httpx.Response(200, json={"stateInstance": "authorized"}))
    route = respx.post(
        "https://api.green-api.com/waInstance123456/sendInteractiveButtons/never-log-this-token"
    ).mock(return_value=httpx.Response(200, json={"idMessage": "accepted"}))
    await send_green_code(config, "+972509876543", "012345")
    import json

    body = json.loads(route.calls.last.request.content)
    assert body["chatId"] == "972509876543@c.us"
    assert body["buttons"] == [
        {"type": "copy", "buttonId": "copy-code", "buttonText": "Copy code", "copyCode": "012345"}
    ]
    assert "never-log-this-token" not in caplog.text


@respx.mock
async def test_greenapi_approval_has_only_link_and_no_login_code() -> None:
    import json

    from app.security.two_factor import send_green_code

    config = {
        "api_url": "https://api.green-api.com",
        "instance_id": "123456",
        "token": "synthetic-provider-token",
    }
    base = "https://api.green-api.com/waInstance123456"
    respx.get(f"{base}/getStateInstance/synthetic-provider-token").mock(
        return_value=httpx.Response(200, json={"stateInstance": "authorized"})
    )
    route = respx.post(f"{base}/sendInteractiveButtons/synthetic-provider-token").mock(
        return_value=httpx.Response(200, json={"idMessage": "accepted"})
    )
    approval_url = "https://iris.example.com/verify-contact?token=synthetic-approval-token"
    await send_green_code(config, "+12025550123", "123456", approval_url)
    body = json.loads(route.calls.last.request.content)
    assert body["header"] == "Approve your Iris WhatsApp number"
    assert approval_url in body["body"]
    assert "123456" not in json.dumps(body)
    assert body["footer"] == "Approval link expires in 30 minutes."
    assert body["buttons"] == [
        {
            "type": "url",
            "buttonId": "approve-contact",
            "buttonText": "Approve WhatsApp",
            "url": approval_url,
        }
    ]


async def test_greenapi_test_gates_enable_and_secret_stays_encrypted(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    assert (await app_client.post("/api/users/security/smtp/test")).json()["ok"]
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 422
    config = (await app_client.get("/api/users/security/config")).json()
    assert config["green_api_token_set"] and not config["green_api"]["verified"]
    assert "test-green-token" not in str(config)
    async with app_client.app.state.session_factory() as db:
        saved = await db.get(Setting, "security.green_api")
        assert saved and saved.is_secret and "test-green-token" not in str(saved.value)
    bad_send = AsyncMock(side_effect=RuntimeError("test-green-token"))
    monkeypatch.setattr("app.api.users.send_green_code", bad_send)
    failure = await app_client.post("/api/users/security/whatsapp/test")
    assert not failure.json()["ok"] and "test-green-token" not in failure.text
    assert (
        await app_client.put(
            "/api/users/security/whatsapp",
            json={
                "api_url": "https://attacker.example",
                "instance_id": "123456",
                "token": "test-green-token",
            },
        )
    ).status_code == 422


async def test_email_approval_uses_public_prefix_and_enables_without_greenapi(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import parse_qs, urlsplit

    sender = await configure(app_client, monkeypatch)
    assert (
        await app_client.put(
            "/api/settings",
            json={"settings": {"runtime.public_base_url": "https://iris.example.com/prefix"}},
        )
    ).status_code == 200
    assert (await app_client.post("/api/users/security/smtp/test")).json()["ok"]
    link = sender.call_args.args[3]
    assert link.startswith("https://iris.example.com/prefix/verify-contact?token=")
    token = parse_qs(urlsplit(link).query)["token"][0]
    # Loading a link does not automatically approve it (mail scanners may load links).
    assert (await app_client.get("/api/users")).json()[0]["email_verified"] is False
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 422
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 200
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 400
    assert (await app_client.get("/api/users/security/config")).json()["green_api"][
        "verified"
    ] is False
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 200
    # An unavailable preference falls back to the approved account channel.
    monkeypatch.setattr(auth, "deliver", AsyncMock())
    app_client.cookies.clear()
    assert (
        await app_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "correct-horse", "channel": "whatsapp"},
        )
    ).json()["channel"] == "email"


async def test_whatsapp_approval_enables_without_smtp(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import parse_qs, urlsplit

    await configure(app_client, monkeypatch)
    send = AsyncMock()
    monkeypatch.setattr("app.api.users.send_green_code", send)
    assert (await app_client.post("/api/users/security/whatsapp/test")).json()["ok"]
    token = parse_qs(urlsplit(send.call_args.args[3]).query)["token"][0]
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 200
    assert (
        await app_client.put("/api/users/security/two-factor", json={"enabled": True})
    ).status_code == 200
    delivery = AsyncMock()
    monkeypatch.setattr("app.security.two_factor.send_green_code", delivery)
    app_client.cookies.clear()
    response = await app_client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
    )
    assert response.status_code == 200 and response.json()["channel"] == "whatsapp"
    delivery.assert_awaited_once()


async def test_changed_contact_invalidates_approval_link(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import parse_qs, urlsplit

    sender = await configure(app_client, monkeypatch)
    assert (await app_client.post("/api/users/security/smtp/test")).json()["ok"]
    token = parse_qs(urlsplit(sender.call_args.args[3]).query)["token"][0]
    assert (
        await app_client.put(
            "/api/users/1",
            json={"username": "admin", "role": "admin", "email": "changed@example.com"},
        )
    ).status_code == 200
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 400
    assert (await app_client.get("/api/users")).json()[0]["email_verified"] is False


async def test_docker_recovery_requires_key_revokes_sessions_and_has_no_http_bypass(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.security.recover_2fa import recover

    await configure(app_client, monkeypatch)
    await enable(app_client)
    cfg = get_settings().model_copy(update={"two_factor_recovery_key": "r" * 48})
    async with app_client.app.state.session_factory() as db:
        with pytest.raises(ValueError, match="incorrect"):
            await recover(db, cfg, "admin", "wrong-key")
        assert (await db.get(Setting, "security.two_factor")).value is True
    assert (await app_client.post("/api/auth/recover", json={"key": "r" * 48})).status_code in (
        404,
        405,
    )
    async with app_client.app.state.session_factory() as db:
        await recover(db, cfg, "admin", "r" * 48)
        assert (await db.get(Setting, "security.two_factor")).value is False
    assert (await app_client.get("/api/auth/me")).status_code == 401
    assert (
        await app_client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-horse"}
        )
    ).status_code == 200


async def test_locked_admin_recovers_after_docker_reset_and_restart(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings
    from app.security.recover_2fa import recover

    await configure(app_client, monkeypatch)
    await enable(app_client)
    credentials = {"username": "admin", "password": "correct-horse"}
    for _ in range(5):
        assert (
            await app_client.post(
                "/api/auth/login", json={**credentials, "password": "wrong-password"}
            )
        ).status_code == 401
    assert (await app_client.post("/api/auth/login", json=credentials)).status_code == 429
    cfg = get_settings().model_copy(update={"two_factor_recovery_key": "r" * 48})
    async with app_client.app.state.session_factory() as db:
        await recover(db, cfg, "admin", "r" * 48)
    assert (await app_client.post("/api/auth/login", json=credentials)).status_code == 429
    # Docker restarts the server process, creating a fresh in-memory limiter.
    auth.limiter = auth.LoginLimiter()
    app_client.cookies.clear()
    response = await app_client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200 and not response.json().get("two_factor_required")
    assert (await app_client.get("/api/auth/me")).status_code == 200


async def test_expired_contact_link_cannot_approve(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from sqlalchemy import select

    from app.security.two_factor import CONTACT_PREFIX

    sender = await configure(app_client, monkeypatch)
    assert (await app_client.post("/api/users/security/smtp/test")).json()["ok"]
    token = parse_qs(urlsplit(sender.call_args.args[3]).query)["token"][0]
    async with app_client.app.state.session_factory() as db:
        row = await db.scalar(select(Setting).where(Setting.key.startswith(CONTACT_PREFIX)))
        value = dict(row.value)
        value["expires"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        row.value = value
        await db.commit()
    assert (
        await app_client.post("/api/auth/confirm-contact", json={"token": token})
    ).status_code == 400


async def test_user_contacts_unique_on_create_and_edit(app_client: Any) -> None:
    first = {
        "username": "first",
        "password": "watch-password",
        "email": "First@example.com",
        "whatsapp_number": "+972509876543",
    }
    response = await app_client.post("/api/users", json=first)
    assert response.status_code == 201
    user_id = response.json()["id"]
    for contact in ({"email": " first@EXAMPLE.com "}, {"whatsapp_number": "+972509876543"}):
        response = await app_client.post(
            "/api/users", json={"username": "duplicate", "password": "watch-password", **contact}
        )
        assert response.status_code == 409 and "already assigned" in response.json()["detail"]
    second = (
        await app_client.post(
            "/api/users", json={"username": "second", "password": "watch-password"}
        )
    ).json()
    assert (
        await app_client.put(
            f"/api/users/{second['id']}", json={"username": "second", "email": "first@example.com"}
        )
    ).status_code == 409
    assert (
        await app_client.put(f"/api/users/{user_id}", json={**first, "password": None})
    ).status_code == 200
    assert (
        await app_client.post(
            "/api/users", json={"username": "third", "password": "watch-password"}
        )
    ).status_code == 201


async def test_only_admin_can_delete_watch_account_and_contacts_can_be_reused(
    app_client: Any,
) -> None:
    response = await app_client.post(
        "/api/users",
        json={
            "username": "removable",
            "password": "watch-password",
            "email": "reusable@example.com",
            "whatsapp_number": "+972509876543",
        },
    )
    user_id = response.json()["id"]
    assert (await app_client.delete("/api/users/1")).status_code == 422
    admin_cookie = app_client.cookies.get("iris_session")
    app_client.cookies.clear()
    assert (
        await app_client.post(
            "/api/auth/login", json={"username": "removable", "password": "watch-password"}
        )
    ).status_code == 200
    assert (await app_client.delete(f"/api/users/{user_id}")).status_code == 403
    app_client.cookies.clear()
    app_client.cookies.set("iris_session", admin_cookie)
    assert (await app_client.delete(f"/api/users/{user_id}")).status_code == 204
    response = await app_client.post(
        "/api/users",
        json={
            "username": "replacement",
            "password": "watch-password",
            "email": "reusable@example.com",
            "whatsapp_number": "+972509876543",
        },
    )
    assert response.status_code == 201


async def test_approval_email_has_link_and_no_login_code() -> None:
    link = "https://iris.example.com/verify-contact?token=approval-token"
    message = smtp_message(SMTP, "user@example.com", "123456", link)
    assert str(message["Subject"]) == "Approve your Iris email address"
    for kind in ("plain", "html"):
        body = message.get_body(preferencelist=(kind,)).get_content()
        assert link in body
        assert "123456" not in body and "verification code" not in body
        assert "30 minutes" in body


@pytest.mark.parametrize("role", ["watch", "parent"])
async def test_monitoring_actions_require_parent_and_settings_require_admin(
    app_client: Any, role: str
) -> None:
    await app_client.post(
        "/api/users", json={"username": "actor", "password": "actor-password", "role": role}
    )
    app_client.cookies.clear()
    assert (
        await app_client.post(
            "/api/auth/login", json={"username": "actor", "password": "actor-password"}
        )
    ).status_code == 200
    for method, path, body in [
        ("DELETE", "/api/media", None),
        ("POST", "/api/review/999", {"resolution": "safe"}),
        ("POST", "/api/alerts/999/resend", None),
        ("PATCH", "/api/alerts/999", {"status": "acknowledged"}),
        ("POST", "/api/messages/999/reprocess", None),
    ]:
        response = await app_client.request(method, path, json=body)
        assert response.status_code == (
            403 if role == "watch" else (200 if path == "/api/media" else 404)
        ), (path, response.text)
    assert (await app_client.get("/api/users")).status_code == 403
    assert (
        await app_client.put("/api/settings", json={"settings": {"alerts.alert_on_review": False}})
    ).status_code == 403


async def test_enabled_two_factor_requires_new_user_contact_and_preserves_other_users_channel(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await configure(app_client, monkeypatch)
    await enable(app_client)
    body = {"username": "parent2", "role": "parent", "password": "a-long-password"}
    assert (await app_client.post("/api/users", json=body)).status_code == 422
    body["email"] = "parent2@example.com"
    created = await app_client.post("/api/users", json=body)
    assert created.status_code == 201
    uid = created.json()["id"]
    async with app_client.app.state.session_factory() as db:
        await db.execute(update(User).where(User.id == uid).values(email_verified=True))
        await db.commit()
    body["email"] = None
    assert (await app_client.put(f"/api/users/{uid}", json=body)).status_code == 422
    async with app_client.app.state.session_factory() as db:
        user = await db.get(User, uid)
        assert user and user.email == "parent2@example.com" and user.email_verified


async def test_omitted_role_and_contacts_preserve_account(app_client: Any):
    response = await app_client.put("/api/users/1", json={"username": "admin"})
    assert response.status_code == 200 and response.json()["role"] == "admin"
    assert (await app_client.get("/api/auth/me")).status_code == 200
