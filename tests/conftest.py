import base64
import os

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    monkeypatch.setenv("IRIS_SECRET_KEY", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("IRIS_PUBLIC_BASE_URL", "http://localhost:8080/")
    monkeypatch.setenv("IRIS_WORKERS", "0")  # tests drive jobs explicitly
    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    get_settings.cache_clear()


def _external_db() -> str | None:
    """The PostgreSQL / MySQL URL the suite runs against, when IRIS_DATABASE_URL points at one."""
    url = os.environ.get("IRIS_DATABASE_URL", "")
    return None if not url or url.startswith("sqlite") else url


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`@pytest.mark.sqlite_only` tests exercise SQLite itself (FTS5, PRAGMAs, file databases)."""
    if _external_db() is None:
        return
    skip = pytest.mark.skip(reason="SQLite-specific")
    for item in items:
        if "sqlite_only" in item.keywords:
            item.add_marker(skip)


async def _empty_database() -> None:
    """Every test starts from empty tables (ids restart at 1, like a new SQLite file)."""
    from sqlalchemy import text

    from app.db.engine import make_engine
    from app.db.models import Base

    engine = make_engine()
    names = [t.name for t in reversed(Base.metadata.sorted_tables)]
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("TRUNCATE " + ", ".join(names) + " RESTART IDENTITY CASCADE"))
        else:
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for name in names:
                await conn.execute(text(f"TRUNCATE TABLE {name}"))
            await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    await engine.dispose()


@pytest.fixture
async def app_client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Logged-in client against the real app (migrated temp DB, lifespan running)."""
    import asyncio

    import httpx

    from app import main
    from app.db.migrate import upgrade_head

    monkeypatch.setenv("IRIS_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("IRIS_ADMIN_PASSWORD", "correct-horse")
    get_settings.cache_clear()
    await asyncio.to_thread(upgrade_head)
    if _external_db():
        await _empty_database()
    app = main.create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        r = await c.post("/api/auth/login", json={"username": "admin", "password": "correct-horse"})
        assert r.status_code == 200
        c.app = app  # type: ignore[attr-defined]
        yield c
