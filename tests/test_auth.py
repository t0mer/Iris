from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api import auth as auth_api
from app.config import get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.migrate import upgrade_head
from app.security.auth import bootstrap_admin


async def test_login_rejects_oversized_password_before_hashing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: object) -> bool:
        pytest.fail("Oversized passwords must not reach Argon2")

    monkeypatch.setattr(auth_api, "verify_password", unexpected)
    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "x" * 257}
    )
    assert response.status_code == 422


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    import asyncio

    monkeypatch.setenv("IRIS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IRIS_ADMIN_PASSWORD", "correct-horse")
    get_settings.cache_clear()
    url = f"sqlite+aiosqlite:///{tmp_path / 'a.db'}"
    await asyncio.to_thread(upgrade_head, url)
    engine = make_engine(url)
    factory = make_session_factory(engine)
    async with factory() as s:
        await bootstrap_admin(s, get_settings())
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(auth_api.router)
    auth_api.limiter = auth_api.LoginLimiter()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    await engine.dispose()


async def _login(c: httpx.AsyncClient, pw: str = "correct-horse") -> httpx.Response:
    return await c.post("/api/auth/login", json={"username": "admin", "password": pw})


async def test_login_cookie_flags_and_me(client: httpx.AsyncClient) -> None:
    r = await _login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=604800" in cookie
    assert (await client.get("/api/auth/me")).json() == {
        "username": "admin",
        "role": "admin",
        "id": 1,
        "language": "system",
    }


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_language_requires_auth_and_validates_supported_preferences(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.patch("/api/auth/language", json={"language": "he"})).status_code == 401
    await _login(client)
    assert (await client.patch("/api/auth/language", json={"language": "fr"})).status_code == 422
    for language in ("he", "en", "system"):
        result = await client.patch("/api/auth/language", json={"language": language})
        assert result.status_code == 200
        assert (await client.get("/api/auth/me")).json()["language"] == language
    await client.patch("/api/auth/language", json={"language": "he"})
    await client.post("/api/auth/logout")
    await _login(client)
    assert (await client.get("/api/auth/me")).json()["language"] == "he"


async def test_forged_cookie_rejected(client: httpx.AsyncClient) -> None:
    client.cookies.set("iris_session", "garbage")
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_rate_limit_sixth_attempt(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        assert (await _login(client, "bad")).status_code == 401
    assert (await _login(client, "bad")).status_code == 429
    assert (await _login(client)).status_code == 429


async def test_change_password(client: httpx.AsyncClient) -> None:
    await _login(client)
    r = await client.post(
        "/api/auth/password",
        json={"current_password": "correct-horse", "new_password": "new-password-1"},
    )
    assert r.status_code == 200
    await client.post("/api/auth/logout")
    client.cookies.clear()
    assert (await _login(client)).status_code == 401
    assert (await _login(client, "new-password-1")).status_code == 200


async def test_password_change_revokes_old_session(client: httpx.AsyncClient) -> None:
    await _login(client)
    old = client.cookies["iris_session"]
    await client.post(
        "/api/auth/password",
        json={"current_password": "correct-horse", "new_password": "new-password-1"},
    )
    client.cookies.clear()
    client.cookies.set("iris_session", old)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_password_change_keeps_the_current_session_signed_in(
    client: httpx.AsyncClient,
) -> None:
    await _login(client)
    r = await client.post(
        "/api/auth/password",
        json={"current_password": "correct-horse", "new_password": "new-password-1"},
    )
    assert r.status_code == 200 and "iris_session" in r.headers["set-cookie"]
    assert (await client.get("/api/auth/me")).status_code == 200  # still logged in


def test_successful_reservation_does_not_clear_other_failed_attempts():
    from app.security.auth import LoginLimiter

    limiter = LoginLimiter()
    for _ in range(4):
        limiter.record_failure("same-ip")
    own_attempt = limiter.record_failure("same-ip")
    limiter.release("same-ip", own_attempt)
    assert not limiter.blocked("same-ip")
    limiter.record_failure("same-ip")
    assert limiter.blocked("same-ip")
