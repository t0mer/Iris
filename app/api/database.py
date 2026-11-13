"""/api/database: which database Iris uses, trying a connection, switching and copying the data."""

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import replace
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.db import url as dburl
from app.db.copy import CopyError, CopyProgress, copy_database
from app.db.engine import make_engine
from app.db.models import Base
from app.db.url import DbConfig
from app.security.auth import admin_user

router = APIRouter(prefix="/api/database", tags=["database"], dependencies=[Depends(admin_user)])
Cfg = Annotated[Settings, Depends(get_settings)]

TEST_TIMEOUT = 12
MAX_TESTS = 10
WINDOW_SECONDS = 300
# The connection test opens a socket to a host the owner typed; keep a stuck page from hammering.
_recent: deque[float] = deque()


def _rate_limited() -> bool:
    now = time.monotonic()
    while _recent and now - _recent[0] > WINDOW_SECONDS:
        _recent.popleft()
    if len(_recent) >= MAX_TESTS:
        return True
    _recent.append(now)
    return False


class DbConfigIn(BaseModel):
    kind: Literal["sqlite", "postgresql", "mysql"]
    host: str = Field(default="", max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    name: str = Field(default="", max_length=128)
    user: str = Field(default="", max_length=128)
    # None or "" keeps the saved password (the page never receives it).
    password: str | None = Field(default=None, max_length=512)
    tls: bool = False


class DbConfigOut(BaseModel):
    kind: str
    host: str
    port: int | None
    name: str
    user: str
    tls: bool
    password_set: bool


class CopyOut(BaseModel):
    state: str
    table: str
    copied: dict[str, int]
    error: str | None


class DbStatus(BaseModel):
    config_error: str | None = None  # the saved choice could not be read
    running: DbConfigOut
    running_source: str  # env | file | default
    saved: DbConfigOut  # what the next start will use
    restart_required: bool
    env_override: bool
    copy_job: CopyOut


class ProbeResult(BaseModel):
    ok: bool
    detail: str
    version: str | None = None
    empty: bool | None = None  # no Iris data yet, so a copy can go here
    warning: str | None = None


def _out(cfg: DbConfig) -> DbConfigOut:
    cfg = cfg.with_defaults()
    return DbConfigOut(
        kind=cfg.kind,
        host=cfg.host,
        port=cfg.port,
        name="" if cfg.kind == "sqlite" else cfg.name,
        user=cfg.user,
        tls=cfg.tls,
        password_set=bool(cfg.password),
    )


def _same(a: DbConfig, b: DbConfig) -> bool:
    return a.with_defaults() == b.with_defaults()


def _progress(request: Request) -> CopyProgress:
    if not hasattr(request.app.state, "db_copy"):
        request.app.state.db_copy = CopyProgress()
    progress: CopyProgress = request.app.state.db_copy
    return progress


def _merge(body: DbConfigIn, saved: DbConfig) -> DbConfig:
    """The typed settings, with the stored password when none was typed for the same account."""
    password = body.password or ""
    cfg = DbConfig(
        kind=body.kind,
        host=body.host.strip(),
        port=body.port,
        name="" if body.kind == "sqlite" else body.name.strip(),
        user=body.user.strip(),
        password=password,
        tls=body.tls,
    )
    cfg = cfg.with_defaults()
    # The stored password goes only to the server it was saved for: pointing the same login at
    # another host, port or database means typing the password again.
    same_target = (
        saved.kind == cfg.kind
        and saved.user == cfg.user
        and saved.host == cfg.host
        and saved.name == cfg.name
        and saved.with_defaults().port == cfg.port
    )
    if not password and same_target:
        cfg = replace(cfg, password=saved.password)
    return cfg


def _why(exc: BaseException) -> str:
    """A reason the owner can act on. The driver's own text is never shown: it can name accounts."""
    name = exc.__class__.__name__
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return "The server did not answer in time. Check the host, the port and the firewall."
    if isinstance(exc, OSError):
        return "Could not reach the server. Check the host and the port."
    low = (name + " " + str(getattr(exc, "orig", ""))).lower()
    if "password" in low or "access denied" in low or "1045" in low:
        return "The user name or password was refused."
    if (
        "invalidcatalogname" in low
        or "unknown database" in low
        or "1049" in low
        or ("database" in low and "does not exist" in low)
    ):
        return "That database does not exist. Create it first, then try again."
    if "ssl" in low or "certificate" in low:
        return "The TLS connection failed. Check the server's certificate or turn TLS off."
    return f"Could not connect ({name})."


async def _probe(cfg: DbConfig) -> ProbeResult:
    engine: AsyncEngine = make_engine(config=cfg)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            if cfg.kind == "sqlite":
                version = (await conn.execute(text("SELECT sqlite_version()"))).scalar_one()
            else:
                version = (await conn.execute(text("SELECT VERSION()"))).scalar_one()
            warning = None
            if cfg.kind == "mysql":
                charset = (await conn.execute(text("SELECT @@character_set_database"))).scalar_one()
                if not str(charset).startswith("utf8mb4"):
                    warning = (
                        f"The database uses {charset}. Create it with utf8mb4 so emoji and "
                        "Hebrew are stored correctly."
                    )
            names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            empty = True
            for table in Base.metadata.sorted_tables:
                if table.name in names:
                    row = (await conn.execute(select(table).limit(1))).first()
                    if row is not None:
                        empty = False
                        break
        detail = "Connected."
        if not empty:
            detail = "Connected. It already holds Iris data, so your data cannot be copied into it."
        return ProbeResult(
            ok=True, detail=detail, version=str(version), empty=empty, warning=warning
        )
    except Exception as exc:
        logger.info("database connection test failed: {}", exc.__class__.__name__)
        return ProbeResult(ok=False, detail=_why(exc))
    finally:
        await engine.dispose()


async def _test(cfg: DbConfig) -> ProbeResult:
    try:
        cfg.validate()
    except ValueError as exc:
        return ProbeResult(ok=False, detail=str(exc).capitalize() + ".")
    try:
        return await asyncio.wait_for(_probe(cfg), TEST_TIMEOUT)
    except TimeoutError:
        return ProbeResult(ok=False, detail=_why(TimeoutError()))


def _status(request: Request, settings: Settings) -> DbStatus:
    running: DbConfig = request.app.state.db_running
    config_error: str | None = None
    try:
        saved, source = dburl.resolve(settings)
    except dburl.DbConfigError as exc:
        saved, source, config_error = running, "default", str(exc)
    p = _progress(request)
    return DbStatus(
        config_error=config_error,
        running=_out(running),
        running_source=request.app.state.db_source,
        saved=_out(saved),
        restart_required=not _same(running, saved),
        env_override=source == "env",
        copy_job=CopyOut(state=p.state, table=p.table, copied=p.copied, error=p.error),
    )


def _saved(settings: Settings) -> DbConfig:
    try:
        return dburl.resolve(settings)[0]
    except dburl.DbConfigError:
        return DbConfig()  # unreadable: whatever is typed replaces it (a stored password is gone)


@router.get("")
async def read_database(request: Request, settings: Cfg) -> DbStatus:
    return _status(request, settings)


@router.post("/test")
async def test_database(body: DbConfigIn, settings: Cfg) -> ProbeResult:
    if _rate_limited():
        raise HTTPException(429, "Too many tests. Wait a few minutes and try again.")
    return await _test(_merge(body, _saved(settings)))


def _fresh_copy_state(request: Request) -> None:
    """A new choice starts a new copy: forget the result of the previous target."""
    if _progress(request).state == "running":
        raise HTTPException(409, "A copy is running. Wait for it to finish.")
    request.app.state.db_copy = CopyProgress()


def _env_locked(settings: Settings) -> bool:
    try:
        return dburl.resolve(settings)[1] == "env"
    except dburl.DbConfigError:
        return False


@router.put("")
async def save_database(body: DbConfigIn, request: Request, settings: Cfg) -> DbStatus:
    if _env_locked(settings):
        raise HTTPException(409, "The database is set by IRIS_DATABASE_URL. Change it there.")
    _fresh_copy_state(request)
    cfg = _merge(body, _saved(settings))
    if cfg.kind == "sqlite":
        dburl.delete_file(settings)  # SQLite is the default: nothing to store
        return _status(request, settings)
    if _rate_limited():
        raise HTTPException(429, "Too many tests. Wait a few minutes and try again.")
    result = await _test(cfg)
    if not result.ok:
        raise HTTPException(422, result.detail)
    dburl.save_file(cfg, settings)
    logger.info("database choice saved: {}", cfg.describe())
    return _status(request, settings)


@router.delete("")
async def use_sqlite_again(request: Request, settings: Cfg) -> DbStatus:
    if _env_locked(settings):
        raise HTTPException(409, "The database is set by IRIS_DATABASE_URL. Change it there.")
    _fresh_copy_state(request)
    dburl.delete_file(settings)
    return _status(request, settings)


@router.get("/copy")
async def copy_status(request: Request) -> CopyOut:
    p = _progress(request)
    return CopyOut(state=p.state, table=p.table, copied=p.copied, error=p.error)


@router.post("/copy", status_code=202)
async def start_copy(request: Request, settings: Cfg) -> CopyOut:
    running: DbConfig = request.app.state.db_running
    target = _saved(settings)
    if _same(running, target):
        raise HTTPException(409, "Save a different database first, then copy your data to it.")
    progress = _progress(request)
    if progress.state == "running":
        raise HTTPException(409, "A copy is already running.")
    if _rate_limited():
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")

    source: AsyncEngine = request.app.state.engine

    async def run() -> None:
        with contextlib.suppress(CopyError):  # the progress object already carries the reason
            await copy_database(source, replace(target), progress)

    request.app.state.db_copy_task = asyncio.create_task(run())
    progress.state = "running"
    return CopyOut(state="running", table="", copied={}, error=None)
