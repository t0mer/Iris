"""Programmatic `alembic upgrade head`."""

from alembic import command
from alembic.config import Config

from app.db.url import DbConfig


def upgrade_head(url: str | None = None, config: DbConfig | None = None) -> None:
    """Migrate the database at `url`, at `config` (keeps its TLS settings) or the configured one."""
    cfg = Config("alembic.ini")
    if url:
        cfg.attributes["url"] = url
    if config is not None:
        cfg.attributes["db_config"] = config
    command.upgrade(cfg, "head")
