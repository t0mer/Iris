"""Retry short, self-contained SQLite writes after their failed session has closed."""

import sqlite3
from asyncio import sleep
from collections.abc import Awaitable, Callable
from functools import wraps

from loguru import logger
from sqlalchemy.exc import OperationalError


def retry_sqlite_busy[**P, T](operation: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Only for operations opening a fresh session per attempt, with no external effects."""

    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        for attempt in range(4):
            try:
                return await operation(*args, **kwargs)
            except OperationalError as exc:
                original = exc.orig
                code = getattr(original, "sqlite_errorcode", 0)
                if (
                    not isinstance(original, sqlite3.OperationalError)
                    or code & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                    or attempt == 3
                ):
                    raise
                # Do not log SQL parameters, message bodies or provider credentials.
                logger.warning("SQLite busy during database operation; retry {} of 3", attempt + 1)
                await sleep(0.25 * 2**attempt)
        raise AssertionError("unreachable")

    return wrapped
