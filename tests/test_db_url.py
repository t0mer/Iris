import json
import stat
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db import url as dburl
from app.db.engine import engine_options, make_engine
from app.db.url import DbConfig, parse_url, resolve

PG = DbConfig(kind="postgresql", host="db.local", name="iris", user="iris", password="p@ss:w/rd")
MY = DbConfig(kind="mysql", host="10.0.0.5", port=3307, name="iris", user="iris", password="x")


def test_default_is_the_sqlite_file_in_the_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_DATABASE_URL", raising=False)
    cfg, source = resolve()
    assert (cfg.kind, source) == ("sqlite", "default")
    assert str(cfg.to_url()).endswith("iris.db") and "sqlite+aiosqlite" in str(cfg.to_url())


@pytest.mark.parametrize(
    ("raw", "kind", "driver"),
    [
        ("postgresql://u:p@h/db", "postgresql", "postgresql+asyncpg"),
        ("postgres://u:p@h:6543/db", "postgresql", "postgresql+asyncpg"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql", "postgresql+asyncpg"),
        ("mysql://u:p@h/db", "mysql", "mysql+aiomysql"),
        ("mysql+aiomysql://u:p@h:3307/db", "mysql", "mysql+aiomysql"),
        ("mariadb://u:p@h/db", "mysql", "mysql+aiomysql"),
    ],
)
def test_urls_are_normalised_to_the_async_drivers(raw: str, kind: str, driver: str) -> None:
    cfg = parse_url(raw)
    assert cfg.kind == kind and cfg.port and cfg.to_url().drivername == driver


def test_special_characters_in_the_password_survive() -> None:
    url = PG.to_url()
    assert url.password == "p@ss:w/rd"
    assert parse_url(url.render_as_string(hide_password=False)).password == "p@ss:w/rd"


def test_mysql_uses_utf8mb4_and_tls_comes_from_the_query() -> None:
    assert MY.to_url().query["charset"] == "utf8mb4"
    assert parse_url("postgresql://u:p@h/db?ssl=true").tls is True
    assert parse_url("postgresql://u:p@h/db").tls is False


@pytest.mark.parametrize(
    "raw", ["oracle://u:p@h/db", "postgresql://u:p@/db", "postgresql://u:p@h", "mysql://@h/db"]
)
def test_bad_urls_are_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_url(raw)


@pytest.mark.parametrize(
    "bad",
    [
        DbConfig(kind="postgresql", host="bad host", name="a", user="b"),
        DbConfig(kind="postgresql", host="h", port=0, name="a", user="b"),
        DbConfig(kind="mysql", host="h", name="", user="b"),
        DbConfig(kind="mysql", host="h", name="a", user=""),
    ],
)
def test_validate_rejects_unusable_settings(bad: DbConfig) -> None:
    with pytest.raises(ValueError):
        bad.validate()


def test_the_description_never_contains_the_password() -> None:
    assert "p@ss" not in PG.describe() and "***" in PG.describe()


def test_env_wins_over_the_file_and_the_file_over_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IRIS_DATABASE_URL", raising=False)
    dburl.save_file(PG)
    cfg, source = resolve()
    assert (source, cfg.host, cfg.password) == ("file", "db.local", "p@ss:w/rd")
    monkeypatch.setenv("IRIS_DATABASE_URL", "mysql://u:p@envhost/db")
    cfg, source = resolve()
    assert (source, cfg.host) == ("env", "envhost")
    monkeypatch.delenv("IRIS_DATABASE_URL")
    dburl.delete_file()
    assert resolve()[1] == "default"


def test_the_file_is_private_and_holds_no_plain_password() -> None:
    dburl.save_file(PG)
    path = dburl.config_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text()
    assert "p@ss" not in text and json.loads(text)["password_enc"]
    assert not path.with_suffix(".tmp").exists()


def test_a_file_made_with_another_secret_key_is_not_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    dburl.save_file(PG)
    monkeypatch.setenv("IRIS_SECRET_KEY", base64.b64encode(b"z" * 32).decode())
    get_settings.cache_clear()
    with pytest.raises(InvalidTag):
        dburl.load_file()


def test_engine_options_per_database() -> None:
    assert engine_options(DbConfig()) == {}
    assert engine_options(PG)["pool_pre_ping"] is True and "isolation_level" not in engine_options(
        PG
    )
    assert engine_options(MY)["isolation_level"] == "READ COMMITTED"
    assert "ssl" in engine_options(DbConfig(**{**PG.__dict__, "tls": True}))["connect_args"]
    assert "ssl" not in engine_options(PG)["connect_args"]
    assert engine_options(PG)["connect_args"]["timeout"] == 10
    assert engine_options(MY)["connect_args"]["connect_timeout"] == 10


async def test_only_sqlite_gets_the_pragmas(tmp_path: Path) -> None:
    from sqlalchemy import text

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    async with engine.connect() as c:
        assert (await c.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"
    await engine.dispose()
    pg = make_engine(config=PG)  # builds without connecting, and without the sqlite listener
    assert make_url(str(pg.url)).drivername == "postgresql+asyncpg"
    await pg.dispose()
