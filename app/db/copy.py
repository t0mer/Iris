"""Copy every row of the running database into an empty one of another kind.

Used by the Settings page when the owner switches databases. The source is only read. Primary
keys are kept (foreign keys and job payloads refer to them) and the target's sequences are moved
past the copied ids.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy import Table, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db.engine import make_engine
from app.db.migrate import upgrade_head
from app.db.models import Base
from app.db.url import DbConfig

BATCH = 500


class CopyError(Exception):
    """A problem the owner can act on; the message is safe to show."""


@dataclass
class CopyProgress:
    state: str = "idle"  # idle | running | done | failed
    table: str = ""
    copied: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def _tables() -> list[Table]:
    return list(Base.metadata.sorted_tables)  # parents before the tables that refer to them


async def count_rows(engine: AsyncEngine, table: Table) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(table))).scalar_one())


async def target_has_data(engine: AsyncEngine) -> bool:
    for table in _tables():
        if await count_rows(engine, table) > 0:
            return True
    return False


async def copy_database(
    source: AsyncEngine,
    target_cfg: DbConfig,
    progress: CopyProgress,
    on_change: Callable[[], None] = lambda: None,
) -> dict[str, int]:
    """Migrate the target's schema, require it to be empty, copy, then verify the row counts.

    All reads happen in one snapshot of the source, so rows written or deleted meanwhile cannot
    break the foreign keys or skip rows. If anything fails after the first row was written, the
    target is emptied again, so the copy can simply be retried.
    """
    progress.state, progress.copied, progress.error = "running", {}, None
    target = make_engine(config=target_cfg)
    started = False
    try:
        await asyncio.to_thread(upgrade_head, None, target_cfg)
        if await target_has_data(target):
            raise CopyError("The new database already contains data. Use an empty database.")
        started = True
        async with source.connect() as src:
            await _begin_snapshot(src)
            expected: dict[str, int] = {}
            for table in _tables():
                progress.table = table.name
                on_change()
                expected[table.name] = int(
                    (await src.execute(select(func.count()).select_from(table))).scalar_one()
                )
                progress.copied[table.name] = await _copy_table(src, target, table)
                on_change()
            await src.rollback()  # read only: ends the snapshot
        await _reset_sequences(target)
        for table in _tables():
            if progress.copied[table.name] != expected[table.name]:
                raise CopyError(f"The copy of {table.name} is incomplete. Nothing was switched.")
            if await count_rows(target, table) != expected[table.name]:
                raise CopyError(f"The copy of {table.name} is incomplete. Nothing was switched.")
        progress.state, progress.table = "done", ""
        logger.info("database copied to {}: {}", target_cfg.describe(), progress.copied)
        return dict(progress.copied)
    except Exception as exc:
        if started:
            await _empty(target)
        if isinstance(exc, CopyError):
            progress.state, progress.error = "failed", str(exc)
            raise
        # Driver messages can name the server or the user: only the class is logged or shown.
        name = exc.__class__.__name__
        logger.error("database copy failed: {}", name)
        progress.state = "failed"
        progress.error = f"The copy stopped ({name}). The old database is untouched."
        raise CopyError(progress.error) from exc
    finally:
        await target.dispose()


async def _begin_snapshot(src: AsyncConnection) -> None:
    """Make every later read see the database as it is now."""
    if src.dialect.name == "sqlite":
        await src.exec_driver_sql("BEGIN")  # a WAL read transaction pins a snapshot
    else:
        await src.execution_options(isolation_level="REPEATABLE READ")


async def _empty(target: AsyncEngine) -> None:
    """Undo a half-finished copy (only ever called on a target that was empty when we started)."""
    try:
        async with target.begin() as conn:
            if target.dialect.name == "mysql":
                await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for table in reversed(_tables()):
                await conn.execute(table.delete())
            if target.dialect.name == "mysql":
                await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    except Exception as exc:
        logger.error("could not empty the target after a failed copy: {}", exc.__class__.__name__)


async def _copy_table(src: AsyncConnection, target: AsyncEngine, table: Table) -> int:
    order = [c for c in table.primary_key.columns] or list(table.columns)
    total, offset = 0, 0
    while True:
        rows = (
            (await src.execute(select(table).order_by(*order).limit(BATCH).offset(offset)))
            .mappings()
            .all()
        )
        if not rows:
            return total
        async with target.begin() as dst:
            await dst.execute(table.insert(), [dict(r) for r in rows])
        total += len(rows)
        offset += BATCH


async def _reset_sequences(target: AsyncEngine) -> None:
    """PostgreSQL does not advance a serial when ids are inserted explicitly."""
    if target.dialect.name != "postgresql":
        return
    async with target.begin() as conn:
        for table in _tables():
            pk = list(table.primary_key.columns)
            if len(pk) == 1 and pk[0].autoincrement is not False and pk[0].type.python_type is int:
                col = pk[0].name
                await conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
                        f"COALESCE((SELECT MAX({col}) FROM {table.name}), 1), "
                        f"(SELECT MAX({col}) FROM {table.name}) IS NOT NULL)"
                    )
                )


def describe_counts(counts: dict[str, int]) -> dict[str, Any]:
    return {k: v for k, v in counts.items() if v}
