"""Transaction-scoped schedule reservation shared by API and background dispatch."""

from sqlalchemy import update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from app.db.models import Setting


async def lock_schedule(db: AsyncSession, key: str) -> None:
    """Hold a database write lock until the caller commits its lookup and inserts."""
    lock_key = "internal.schedule_reservation." + key
    values = {"key": lock_key, "value": {}, "is_secret": False}
    dialect = db.get_bind().dialect.name
    if dialect == "mysql":
        insert = mysql_insert(Setting).values(**values)
        statement: Insert = insert.on_duplicate_key_update(key=insert.inserted.key)
    else:
        insert_fn = postgres_insert if dialect == "postgresql" else sqlite_insert
        statement = insert_fn(Setting).values(**values).on_conflict_do_nothing()
    await db.execute(statement)
    # A no-op UPDATE takes a row lock on PostgreSQL/MySQL and the SQLite writer
    # lock. A SELECT before this lock could observe a stale empty job queue.
    await db.execute(update(Setting).where(Setting.key == lock_key).values(key=lock_key))
