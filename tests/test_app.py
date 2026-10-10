from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app import main
from app.config import get_settings
from app.db.migrate import upgrade_head
from app.version import VERSION


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    import asyncio

    monkeypatch.setenv("IRIS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IRIS_ADMIN_PASSWORD", "correct-horse")
    get_settings.cache_clear()
    await asyncio.to_thread(upgrade_head)
    app = main.create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def test_health_and_version(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert (await client.get("/api/version")).json() == {"version": VERSION}


async def test_security_headers(client: httpx.AsyncClient) -> None:
    h = (await client.get("/api/health")).headers
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert h["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in h["content-security-policy"]


async def test_docs_and_schema_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/docs")).status_code == 401
    assert (await client.get("/api/openapi.json")).status_code == 401
    await client.post("/api/auth/login", json={"username": "admin", "password": "correct-horse"})
    assert (await client.get("/api/docs")).status_code == 200
    schema = await client.get("/api/openapi.json")
    assert schema.status_code == 200 and "/api/alerts" in schema.json()["paths"]


async def test_unknown_api_path_404_not_spa(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/nope")).status_code == 404


async def test_spa_fallback(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("<html>iris</html>")
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path)
    r = await client.get("/alerts/3")
    assert r.status_code == 200 and "iris" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert (await client.get("/assets/obsolete-page.js")).status_code == 404
    assert (await client.get("/../../etc/passwd")).status_code in (200, 404)


async def test_nul_byte_path_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/a%00b")).status_code in (200, 404)
