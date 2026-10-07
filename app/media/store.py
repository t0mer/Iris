"""Where kept media lives: a folder on this server or an S3-compatible bucket.

Keys are plain relative paths (`media/{message_id}/{hash}.jpg`) and are validated, so a key can
never point outside the store. Errors carry short static messages that are safe to show.
"""

import asyncio
import os
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

CHUNK = 64 * 1024
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,400}$")


class MediaStoreError(Exception):
    """A storage problem; the message is static and never contains keys, hosts or secrets."""


class MediaStore(Protocol):
    name: str

    async def put(self, key: str, path: Path, content_type: str) -> None: ...

    def open(self, key: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        """Stream the bytes from `start` up to and including `end` (the whole object by default)."""
        ...

    async def delete(self, key: str) -> None: ...

    async def probe(self) -> None:
        """Write, read back and delete a tiny object; raise MediaStoreError if anything fails."""
        ...

    async def aclose(self) -> None: ...


def check_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key.split("/") or "//" in key or key.endswith("/"):
        raise MediaStoreError("Invalid storage key.")
    return key


class LocalStore:
    """Files under one folder (owner-only permissions), written atomically."""

    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / check_key(key)).resolve()
        if self.root.resolve() not in path.parents:
            raise MediaStoreError("Invalid storage key.")
        return path

    async def put(self, key: str, path: Path, content_type: str) -> None:
        dest = self._path(key)

        def write() -> None:
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = dest.with_suffix(dest.suffix + ".part")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as out, path.open("rb") as src:
                shutil.copyfileobj(src, out, CHUNK)
            os.replace(tmp, dest)

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise MediaStoreError("Could not write to the media folder.") from exc

    async def open(self, key: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        path = self._path(key)
        try:
            handle = await asyncio.to_thread(path.open, "rb")
        except FileNotFoundError as exc:
            raise MediaStoreError("The media file is gone.") from exc
        try:
            await asyncio.to_thread(handle.seek, start)
            left = None if end is None else end - start + 1
            while left is None or left > 0:
                chunk = await asyncio.to_thread(
                    handle.read, CHUNK if left is None else min(CHUNK, left)
                )
                if not chunk:
                    break
                if left is not None:
                    left -= len(chunk)
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def remove() -> None:
            path.unlink(missing_ok=True)
            parent, root = path.parent, self.root.resolve()
            while parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()  # drop emptied message folders
                parent = parent.parent

        try:
            await asyncio.to_thread(remove)
        except OSError as exc:
            raise MediaStoreError("Could not delete the media file.") from exc

    async def probe(self) -> None:
        probe = self.root / ".probe"
        try:
            await asyncio.to_thread(self.root.mkdir, 0o700, True, True)
            await asyncio.to_thread(probe.write_bytes, b"iris")
            if await asyncio.to_thread(probe.read_bytes) != b"iris":
                raise MediaStoreError("The media folder returned different data.")
            await asyncio.to_thread(probe.unlink)
        except OSError as exc:
            raise MediaStoreError("The media folder is not writable.") from exc

    async def aclose(self) -> None:
        return None
