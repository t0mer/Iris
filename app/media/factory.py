"""Build the configured media store from the settings (and, for a test, the unsaved form)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StoredMedia
from app.media.s3 import S3Config, S3Store, validate_endpoint
from app.media.store import LocalStore, MediaStore, MediaStoreError
from app.settings_store import get_secret, get_setting


@dataclass
class MediaOverrides:
    """Values typed on the settings page; None or blank falls back to what is saved."""

    backend: str | None = None
    endpoint: str | None = None
    bucket: str | None = None
    region: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    prefix: str | None = None
    path_style: bool | None = None


def overrides_for(row: StoredMedia) -> MediaOverrides:
    """Where this file really lives (not where the settings point today)."""
    if row.backend == "s3" and row.location:
        try:
            loc = json.loads(row.location)
            return MediaOverrides(
                backend="s3",
                endpoint=loc["endpoint"],
                bucket=loc["bucket"],
                region=loc.get("region"),
                prefix=loc.get("prefix", ""),
                path_style=bool(loc.get("path_style", True)),
            )
        except (ValueError, KeyError):
            pass
    return MediaOverrides(backend=row.backend)


async def build_store(
    db: AsyncSession,
    key_bytes: bytes,
    data_dir: Path,
    overrides: MediaOverrides | None = None,
) -> MediaStore:
    o = overrides or MediaOverrides()
    backend = o.backend or str(await get_setting(db, "media.backend"))
    if backend == "local":
        return LocalStore(data_dir / "media")

    async def pick(typed: str | None, key: str) -> str | None:
        return typed.strip() if typed and typed.strip() else await get_setting(db, key)

    endpoint = await pick(o.endpoint, "media.s3_endpoint")
    bucket = await pick(o.bucket, "media.s3_bucket")
    access = await pick(o.access_key, "media.s3_access_key")
    secret = o.secret_key or await get_secret(db, "media.s3_secret_key", key_bytes)
    if not (endpoint and bucket and access and secret):
        raise MediaStoreError("Enter the endpoint, bucket, access key and secret key.")
    try:
        endpoint = validate_endpoint(endpoint)
    except ValueError as exc:
        raise MediaStoreError(str(exc)) from exc
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]", bucket):
        raise MediaStoreError("The bucket name is not valid.")
    return S3Store(
        S3Config(
            endpoint=endpoint,
            bucket=bucket,
            access_key=access,
            secret_key=secret,
            region=(await pick(o.region, "media.s3_region")) or "auto",
            prefix=(
                o.prefix if o.prefix is not None else str(await get_setting(db, "media.s3_prefix"))
            ),
            path_style=(
                o.path_style
                if o.path_style is not None
                else bool(await get_setting(db, "media.s3_path_style"))
            ),
        )
    )
