import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.media import s3
from app.media.s3 import S3Config, S3Store, sigv4_headers, validate_endpoint
from app.media.store import MediaStoreError

SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
CFG = S3Config(
    endpoint="https://s3.example.com",
    bucket="iris-media",
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key=SECRET,
    region="auto",
    prefix="iris/",
)


class Server:
    """An in-memory S3 that records every request."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(
                self.fail, text=f"<Error>secret {SECRET} bucket iris-media</Error>"
            )
        path = request.url.path
        if request.method == "PUT":
            self.objects[path] = request.content
            return httpx.Response(200)
        if request.method == "DELETE":
            self.objects.pop(path, None)
            return httpx.Response(204)
        if path not in self.objects:
            return httpx.Response(404)
        data = self.objects[path]
        rng = request.headers.get("range")
        if rng:
            a, b = rng.removeprefix("bytes=").split("-")
            part = data[int(a) : (int(b) + 1 if b else None)]
            return httpx.Response(206, content=part)
        return httpx.Response(200, content=data)


def _store(server: Server, cfg: S3Config = CFG) -> S3Store:
    return S3Store(cfg, transport=httpx.MockTransport(server))


def _file(tmp_path: Path, data: bytes = b"hello world") -> Path:
    p = tmp_path / "f.bin"
    p.write_bytes(data)
    return p


def test_signature_matches_the_published_aws_example() -> None:
    """GET Object with a Range header, from the AWS Signature V4 documentation for S3."""
    headers = sigv4_headers(
        "GET",
        "examplebucket.s3.amazonaws.com",
        "/test.txt",
        "",
        {"Range": "bytes=0-9"},
        hashlib.sha256(b"").hexdigest(),
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key=SECRET,
        region="us-east-1",
        now=datetime(2013, 5, 24, 0, 0, 0, tzinfo=UTC),
    )
    assert headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


async def test_put_get_delete_round_trip_path_style(tmp_path: Path) -> None:
    server = Server()
    store = _store(server)
    await store.put("media/1/a.jpg", _file(tmp_path), "image/jpeg")
    put = server.requests[0]
    assert str(put.url) == "https://s3.example.com/iris-media/iris/media/1/a.jpg"
    assert put.headers["content-type"] == "image/jpeg"
    assert put.headers["x-amz-content-sha256"] == hashlib.sha256(b"hello world").hexdigest()
    auth = put.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/")
    assert "/auto/s3/aws4_request" in auth and SECRET not in json.dumps(dict(put.headers))
    assert b"".join([c async for c in store.open("media/1/a.jpg")]) == b"hello world"
    assert b"".join([c async for c in store.open("media/1/a.jpg", 6, 10)]) == b"world"
    assert server.requests[-1].headers["range"] == "bytes=6-10"
    await store.delete("media/1/a.jpg")
    await store.delete("media/1/a.jpg")  # already gone is fine
    await store.aclose()


async def test_virtual_hosted_style_and_a_base_path(tmp_path: Path) -> None:
    server = Server()
    cfg = S3Config(
        **{**CFG.__dict__, "path_style": False, "endpoint": "https://s3.eu-west-1.amazonaws.com"}
    )
    await _store(server, cfg).put("media/2/b.png", _file(tmp_path), "image/png")
    assert (
        str(server.requests[0].url)
        == "https://iris-media.s3.eu-west-1.amazonaws.com/iris/media/2/b.png"
    )
    cfg = S3Config(**{**CFG.__dict__, "endpoint": "http://seaweed.lan:8333/s3"})
    server = Server()
    await _store(server, cfg).put("media/2/b.png", _file(tmp_path), "image/png")
    assert str(server.requests[0].url) == "http://seaweed.lan:8333/s3/iris-media/iris/media/2/b.png"
    assert server.requests[0].headers["host"] == "seaweed.lan:8333"


@pytest.mark.parametrize(
    ("status", "text"),
    [(403, "refused the access key"), (404, "not found"), (500, "HTTP 500")],
)
async def test_errors_are_short_and_never_echo_the_server(
    tmp_path: Path, status: int, text: str
) -> None:
    server = Server()
    server.fail = status
    store = _store(server)
    with pytest.raises(MediaStoreError) as err:
        await store.put("media/3/c.jpg", _file(tmp_path), "image/jpeg")
    msg = str(err.value)
    assert text in msg and SECRET not in msg and "iris-media" not in msg and "c.jpg" not in msg
    with pytest.raises(MediaStoreError):
        [c async for c in store.open("media/3/c.jpg")]


async def test_an_unreachable_endpoint_is_explained(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to s3.example.com")

    store = S3Store(CFG, transport=httpx.MockTransport(boom))
    with pytest.raises(MediaStoreError, match="Could not reach") as err:
        await store.put("media/4/d.jpg", _file(tmp_path), "image/jpeg")
    assert "s3.example.com" not in str(err.value)


async def test_probe_writes_reads_and_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fine(endpoint: str) -> None:
        return None

    monkeypatch.setattr(s3, "refuse_blocked_resolution", fine)
    server = Server()
    await _store(server).probe()
    assert [r.method for r in server.requests] == ["PUT", "GET", "DELETE"]
    assert not server.objects


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://x.example",
        "s3.example.com",
        "http://169.254.169.254/latest",
        "http://metadata.google.internal",
        "http://[fd00:ec2::254]/",
        "http://user:pw@s3.example.com",
        "https://s3.example.com/?x=1",
        "http://0.0.0.0:9000",
    ],
)
def test_bad_endpoints_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_endpoint(bad)


@pytest.mark.parametrize(
    "ok",
    ["https://acct.r2.cloudflarestorage.com", "http://192.168.1.20:8333/", "http://minio:9000"],
)
def test_normal_endpoints_pass(ok: str) -> None:
    assert validate_endpoint(ok) == ok.rstrip("/")


async def test_a_name_that_resolves_to_the_metadata_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(host: str, port: Any) -> list[Any]:
        return [(2, 1, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(s3.socket, "getaddrinfo", fake)
    with pytest.raises(MediaStoreError, match="not allowed"):
        await s3.refuse_blocked_resolution("https://innocent.example.com")
