"""Bootstrap settings loaded from IRIS_* environment variables."""

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_public_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or any(c.isspace() for c in value)
        ):
            raise ValueError("Use a full http(s) Iris URL without credentials, query or fragment")
        _ = parts.port
    except ValueError as exc:
        raise ValueError(
            "Use a valid http(s) Iris base URL, such as https://iris.example.com"
        ) from exc
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IRIS_", env_file=".env", extra="ignore")

    alert_channel: Literal["openwa", "telegram", "smtp", "greenapi"] = "openwa"
    alert_recipients: str | None = None
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_chat_id: str | None = None
    greenapi_api_url: str = "https://api.green-api.com"
    greenapi_media_url: str | None = None
    greenapi_instance_id: str | None = None
    greenapi_token: str | None = Field(default=None, repr=False)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_tls: Literal["starttls", "ssl"] = "starttls"
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_sender: str | None = None
    two_factor_recovery_key: str | None = Field(default=None, repr=False)

    openwa_url: str | None = Field(default=None, validation_alias="OPENWA_URL")
    openwa_api_key: str | None = Field(default=None, validation_alias="OPENWA_API_KEY")
    secret_key: str
    public_base_url: str
    webhook_base_url: str | None = None
    admin_username: str | None = None
    admin_password: str | None = None
    data_dir: Path = Path("/data")
    openwa_storage_report: Path | None = None
    openwa_data_dir: Path | None = None  # optional read-only provider volume for space measurements
    # Deployment metadata: OpenWA 0.24 does not expose archive controls through its API.
    openwa_archive_enabled: bool | None = None
    openwa_archive_outbound: bool | None = None
    openwa_archive_ttl_days: int | None = Field(default=None, ge=0)
    openwa_media_timeout_seconds: int | None = Field(default=None, ge=1)
    port: int = 8080
    workers: int = Field(default=3, ge=0)  # 0 disables the pool (tests)
    log_level: str = "INFO"
    log_json: bool = False
    # Optional bearer token for /metrics. Unset = open (spec); set it when the port is reachable
    # from outside, because OpenWA needs the same port for webhooks.
    metrics_token: str | None = None
    classification_provider: Literal["openai", "ollama"] = "openai"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b-q8_0"
    whisper_url: str | None = None
    transcription_provider: Literal["openai", "cloudflare", "local_whisper"] | None = None
    whisper_api_key: str | None = None
    whisper_model: str = "auto"
    whisper_fallback_model: str | None = None
    # Additional safeguards are explicit opt-ins; existing deployments keep their behavior.
    local_safety_mode: bool = False
    delivery_workers: int = Field(default=0, ge=0, le=4)
    job_timeout_seconds: int = Field(default=900, ge=1, le=3600)
    job_heartbeat_seconds: int = Field(default=0, ge=0, le=120)
    monitoring_silence_minutes: int = Field(default=0, ge=0)
    require_webhook_signatures: bool = False

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
        return validate_public_base_url(v)

    @field_validator("webhook_base_url")
    @classmethod
    def _webhook_url(cls, value: str | None) -> str | None:
        return validate_public_base_url(value) if value else None

    @property
    def webhook_url_base(self) -> str:
        return self.webhook_base_url or self.public_base_url

    @property
    def key_bytes(self) -> bytes:
        return base64.b64decode(self.secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
