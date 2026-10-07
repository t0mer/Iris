import os
import stat
from pathlib import Path

import pytest

from app.media.store import LocalStore, MediaStoreError, check_key


async def _read(store: LocalStore, key: str, start: int = 0, end: int | None = None) -> bytes:
    return b"".join([c async for c in store.open(key, start, end)])


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    return LocalStore(tmp_path / "media")


def _src(tmp_path: Path, data: bytes = b"0123456789" * 10) -> Path:
    p = tmp_path / "src.bin"
    p.write_bytes(data)
    return p


async def test_put_open_and_delete(store: LocalStore, tmp_path: Path) -> None:
    await store.put("media/7/abc.jpg", _src(tmp_path), "image/jpeg")
    assert await _read(store, "media/7/abc.jpg") == b"0123456789" * 10
    await store.delete("media/7/abc.jpg")
    with pytest.raises(MediaStoreError):
        await _read(store, "media/7/abc.jpg")
    assert not (store.root / "media" / "7").exists()  # the emptied folder goes too
    await store.delete("media/7/abc.jpg")  # deleting twice is fine


async def test_ranges_are_inclusive_like_http(store: LocalStore, tmp_path: Path) -> None:
    await store.put("media/1/a.mp4", _src(tmp_path), "video/mp4")
    assert await _read(store, "media/1/a.mp4", 10, 19) == b"0123456789"
    assert await _read(store, "media/1/a.mp4", 95) == b"56789"
    assert await _read(store, "media/1/a.mp4", 0, 0) == b"0"


async def test_files_are_private_and_written_atomically(store: LocalStore, tmp_path: Path) -> None:
    await store.put("media/2/a.jpg", _src(tmp_path), "image/jpeg")
    path = store.root / "media/2/a.jpg"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(store.root.rglob("*.part"))


@pytest.mark.parametrize(
    "key",
    ["../x", "a/../../x", "/etc/passwd", "a//b", "", "a/", ".hidden", "a b", "a\\b", "x" * 500],
)
def test_bad_keys_are_refused(key: str) -> None:
    with pytest.raises(MediaStoreError):
        check_key(key)


async def test_a_key_cannot_escape_the_folder(store: LocalStore, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.mkdir()
    os.symlink(outside, store.root / "link")  # a symlink inside the folder must not lead out
    with pytest.raises(MediaStoreError):
        await store.put("link/x.jpg", _src(tmp_path), "image/jpeg")
    for key in ("../outside/x.jpg", "media/../../outside/x.jpg"):
        with pytest.raises(MediaStoreError):
            await store.put(key, _src(tmp_path), "image/jpeg")
    assert not (outside / "x.jpg").exists()


async def test_probe_checks_the_folder(store: LocalStore, tmp_path: Path) -> None:
    await store.probe()
    assert not (store.root / ".probe").exists()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(MediaStoreError, match="not writable"):
        await LocalStore(blocker / "sub").probe()


async def test_error_messages_never_contain_paths(store: LocalStore, tmp_path: Path) -> None:
    with pytest.raises(MediaStoreError) as err:
        await _read(store, "media/9/missing.jpg")
    assert str(tmp_path) not in str(err.value) and "missing" not in str(err.value)


def test_no_leftover_part_files_after_a_failed_write(tmp_path: Path) -> None:
    import asyncio

    store = LocalStore(tmp_path / "media")
    asyncio.run(store.put("media/1/a.jpg", _src(tmp_path), "image/jpeg"))
    with pytest.raises(MediaStoreError):
        asyncio.run(store.put("media/1/b.jpg", tmp_path / "missing", "image/jpeg"))
    assert not list(store.root.rglob("*.part"))
