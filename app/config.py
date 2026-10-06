"""Bootstrap settings loaded from IRIS_* environment variables."""

import base64
import binascii
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IRIS_", env_file=".env", extra="ignore")

    secret_key: str
    public_base_url: str
    admin_username: str | None = None
    admin_password: str | None = None
    data_dir: Path = Path("/data")
    port: int = 8080
    workers: int = Field(default=3, ge=0)  # 0 disables the pool (tests)
    log_level: str = "INFO"
    log_json: bool = False
    # Optional bearer token for /metrics. Unset = open (spec); set it when the port is reachable
    # from outside, because OpenWA needs the same port for webhooks.
    metrics_token: str | None = None

    @field_validator("secret_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("IRIS_SECRET_KEY must be base64") from exc
        if len(raw) != 32:
            raise ValueError("IRIS_SECRET_KEY must decode to exactly 32 bytes")
        return v

    @field_validator("public_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def key_bytes(self) -> bytes:
        return base64.b64decode(self.secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
