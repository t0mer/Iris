"""The S3 store against a real server (SeaweedFS, MinIO, R2, AWS).

Needs IRIS_TEST_S3_ENDPOINT, IRIS_TEST_S3_BUCKET (must exist), IRIS_TEST_S3_ACCESS_KEY and
IRIS_TEST_S3_SECRET_KEY, plus optionally IRIS_TEST_S3_REGION. Run with `pytest -m integration`.
"""

import os
from pathlib import Path

import pytest

from app.media.s3 import S3Config, S3Store
from app.media.store import MediaStoreError

pytestmark = pytest.mark.integration


def _cfg(secret: str | None = None) -> S3Config:
    env = os.environ
    if not env.get("IRIS_TEST_S3_ENDPOINT"):
        pytest.skip("no test S3 server configured")
    return S3Config(
        endpoint=env["IRIS_TEST_S3_ENDPOINT"],
        bucket=env["IRIS_TEST_S3_BUCKET"],
        access_key=env["IRIS_TEST_S3_ACCESS_KEY"],
        secret_key=secret or env["IRIS_TEST_S3_SECRET_KEY"],
        region=env.get("IRIS_TEST_S3_REGION", "us-east-1"),
        prefix="iris-test/",
    )


async def test_round_trip_ranges_and_delete(tmp_path: Path) -> None:
    store = S3Store(_cfg())
    await store.probe()
    data = bytes(range(256)) * 4000
    src = tmp_path / "f.bin"
    src.write_bytes(data)
    await store.put("media/1/real.bin", src, "application/octet-stream")
    assert b"".join([c async for c in store.open("media/1/real.bin")]) == data
    assert (
        b"".join([c async for c in store.open("media/1/real.bin", 1000, 1999)]) == data[1000:2000]
    )
    await store.delete("media/1/real.bin")
    with pytest.raises(MediaStoreError, match="not found"):
        [c async for c in store.open("media/1/real.bin")]
    await store.aclose()


async def test_a_wrong_secret_is_refused(tmp_path: Path) -> None:
    store = S3Store(_cfg("definitely-wrong-secret"))
    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    with pytest.raises(MediaStoreError, match="refused"):
        await store.put("media/1/x.bin", src, "application/octet-stream")
    await store.aclose()
