import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.db.engine import make_engine
from app.db.models import Base
from app.db.url import resolve

target_metadata = Base.metadata


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    # The FTS5 virtual table and its shadow tables are managed by hand in migrations.
    return not (type_ == "table" and name is not None and name.startswith("messages_fts"))


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=_include_object
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    url = context.config.attributes.get("url")
    engine = make_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


def _run_offline() -> None:
    """`alembic upgrade head --sql`: render the DDL for a dialect without connecting."""
    url = context.config.attributes.get("url") or resolve()[0].to_url().render_as_string(
        hide_password=False
    )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=_include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    _run_offline()
else:
    asyncio.run(_run_async())
