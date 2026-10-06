"""Async engine and session factory for SQLite (default), PostgreSQL and MySQL."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.url import DbConfig, resolve


def db_url() -> str:
    """The URL of the configured database (with the password; never log it)."""
    return resolve()[0].to_url().render_as_string(hide_password=False)


def engine_options(cfg: DbConfig) -> dict[str, Any]:
    if cfg.kind == "sqlite":
        return {}
    opts: dict[str, Any] = {"pool_pre_ping": True, "pool_recycle": 1800}
    if cfg.kind == "mysql":
        # Iris's read-then-update patterns assume each statement sees committed data.
        opts["isolation_level"] = "READ COMMITTED"
    args = cfg.connect_args()
    if args:
        opts["connect_args"] = args
    return opts


def make_engine(url: str | None = None, *, config: DbConfig | None = None) -> AsyncEngine:
    """Engine for an explicit URL (tests, migrations), an explicit config, or the configured one."""
    if url is not None:
        engine = create_async_engine(url)
        sqlite = url.startswith("sqlite")
    else:
        cfg = (config or resolve()[0]).with_defaults()
        engine = create_async_engine(cfg.to_url(), **engine_options(cfg))
        sqlite = cfg.kind == "sqlite"

    if sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _pragmas(dbapi_conn: Any, _rec: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
