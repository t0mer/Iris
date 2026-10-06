"""Where Iris keeps its data: SQLite (default), PostgreSQL or MySQL.

The choice cannot live in the database (settings are read from it), so it comes from, in order:
1. `IRIS_DATABASE_URL`, for Docker and other deployments that configure through the environment;
2. `{IRIS_DATA_DIR}/database.json`, written by the Settings page (the password is encrypted with
   `IRIS_SECRET_KEY`);
3. the SQLite file in the data directory.
"""

import json
import os
import re
import ssl
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.engine import URL, make_url

from app.config import Settings, get_settings
from app.security.crypto import decrypt, encrypt

Kind = Literal["sqlite", "postgresql", "mysql"]
Source = Literal["env", "file", "default"]

KINDS: tuple[Kind, ...] = ("sqlite", "postgresql", "mysql")
DEFAULT_PORTS: dict[str, int] = {"postgresql": 5432, "mysql": 3306}
DRIVERS = {
    "sqlite": "sqlite+aiosqlite",
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
}
CONFIG_FILE = "database.json"
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,253}$")
_ALIASES = {
    "sqlite": "sqlite",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
}


class DbConfigError(Exception):
    """The saved database choice cannot be used. The message is safe to show and to log."""


@dataclass(frozen=True)
class DbConfig:
    kind: Kind = "sqlite"
    host: str = ""
    port: int | None = None
    name: str = ""  # database name; for SQLite an optional file path
    user: str = ""
    password: str = ""
    tls: bool = False

    def validate(self) -> None:
        if self.kind not in KINDS:
            raise ValueError("unknown database type")
        if self.kind == "sqlite":
            return
        if not _HOST_RE.match(self.host):
            raise ValueError("enter a host name or IP address")
        if self.port is not None and not 1 <= self.port <= 65535:
            raise ValueError("the port must be between 1 and 65535")
        if not self.name.strip():
            raise ValueError("enter the database name")
        if not self.user.strip():
            raise ValueError("enter the database user")

    def with_defaults(self) -> "DbConfig":
        if self.kind in DEFAULT_PORTS and self.port is None:
            return replace(self, port=DEFAULT_PORTS[self.kind])
        return self

    def to_url(self, data_dir: Path | None = None) -> URL:
        if self.kind == "sqlite":
            path = self.name or str((data_dir or get_settings().data_dir) / "iris.db")
            return URL.create(DRIVERS["sqlite"], database=path)
        query = {"charset": "utf8mb4"} if self.kind == "mysql" else {}
        return URL.create(
            DRIVERS[self.kind],
            username=self.user,
            password=self.password or None,
            host=self.host,
            port=self.port or DEFAULT_PORTS[self.kind],
            database=self.name,
            query=query,
        )

    def describe(self) -> str:
        """Safe for logs and screens: never contains the password."""
        return self.to_url().render_as_string(hide_password=True)

    def connect_args(self) -> dict[str, Any]:
        """TLS with the system trust store (a private CA belongs in the system store)."""
        if self.kind == "sqlite":
            return {}
        args: dict[str, Any] = {"timeout" if self.kind == "postgresql" else "connect_timeout": 10}
        if self.tls:
            args["ssl"] = ssl.create_default_context()
        return args


def parse_url(raw: str) -> DbConfig:
    """Read `IRIS_DATABASE_URL` (sqlite:///path, postgresql://..., mysql://...)."""
    url = make_url(raw)
    kind = _ALIASES.get(url.get_backend_name())
    if kind is None:
        raise ValueError("IRIS_DATABASE_URL must start with sqlite, postgresql or mysql")
    if kind == "sqlite":
        return DbConfig(kind="sqlite", name=url.database or "")
    tls = str(url.query.get("ssl", url.query.get("tls", ""))).lower() in ("1", "true", "require")
    cfg = DbConfig(
        kind=kind,  # type: ignore[arg-type]
        host=url.host or "",
        port=url.port,
        name=url.database or "",
        user=url.username or "",
        password=url.password or "",
        tls=tls,
    )
    cfg.validate()
    return cfg.with_defaults()


def config_path(data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / CONFIG_FILE


def load_file(settings: Settings | None = None) -> DbConfig | None:
    s = settings or get_settings()
    path = config_path(s.data_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        enc = raw.get("password_enc")
        cfg = DbConfig(
            kind=raw["kind"],
            host=raw.get("host", ""),
            port=raw.get("port"),
            name=raw.get("name", ""),
            user=raw.get("user", ""),
            password=decrypt(s.key_bytes, enc) if enc else "",
            tls=bool(raw.get("tls", False)),
        )
        cfg.validate()
    except Exception as exc:
        # Never fall back to another database silently: new messages would end up in the wrong one.
        raise DbConfigError(
            f"{path} cannot be read ({exc.__class__.__name__}). Restore the IRIS_SECRET_KEY it "
            "was saved with, or delete the file to use SQLite again."
        ) from None
    return cfg


def save_file(cfg: DbConfig, settings: Settings | None = None) -> None:
    """Write the choice atomically with owner-only permissions; the password is encrypted."""
    s = settings or get_settings()
    cfg.validate()
    body = {
        "kind": cfg.kind,
        "host": cfg.host,
        "port": cfg.port,
        "name": cfg.name,
        "user": cfg.user,
        "password_enc": encrypt(s.key_bytes, cfg.password) if cfg.password else "",
        "tls": cfg.tls,
    }
    path = config_path(s.data_dir)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, path)


def delete_file(settings: Settings | None = None) -> None:
    config_path((settings or get_settings()).data_dir).unlink(missing_ok=True)


def resolve(settings: Settings | None = None) -> tuple[DbConfig, Source]:
    s = settings or get_settings()
    env = os.environ.get("IRIS_DATABASE_URL", "").strip()
    if env:
        return parse_url(env), "env"
    saved = load_file(s)
    if saved is not None:
        return saved.with_defaults(), "file"
    return DbConfig(), "default"
