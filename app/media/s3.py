"""A small S3 client (AWS Signature V4 over httpx) for AWS S3, Cloudflare R2, SeaweedFS and MinIO.

Only what Iris needs: put, ranged get, delete. It signs the payload hash, so it also works against
plain-http servers on a LAN. Errors become short static messages: the endpoint, bucket, key and
the server's own text never appear in them.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import tempfile
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

from app.media.store import CHUNK, MediaStoreError, check_key
from app.metrics import record_provider

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_BLOCKED_NAMES = {"metadata.google.internal", "metadata", "instance-data"}
_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    bucket: str
    access_key: str
    secret_key: str
    region: str = "auto"
    prefix: str = "iris/"
    path_style: bool = True


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4_headers(
    method: str,
    host: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    payload_hash: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
    service: str = "s3",
) -> dict[str, str]:
    """Headers to send (incl. Authorization). `headers` are signed in addition to host/date/hash."""
    amzdate = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    day = amzdate[:8]
    signed = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    signed |= {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amzdate}
    names = sorted(signed)
    canonical = "\n".join(
        [
            method,
            path,
            query,
            "".join(f"{n}:{signed[n]}\n" for n in names),
            ";".join(names),
            payload_hash,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amzdate, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(
        _hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request"
    )
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in headers.items()}
    out |= {"x-amz-content-sha256": payload_hash, "x-amz-date": amzdate}
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return out


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip == _METADATA_V6


def validate_endpoint(endpoint: str) -> str:
    """Normalise the endpoint URL; refuse anything that is not a plain http(s) host."""
    parts = urlsplit(endpoint.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The endpoint must start with http:// or https:// and name a host.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("The endpoint must be just a host (and optional port and path).")
    host = parts.hostname.lower()
    if host in _BLOCKED_NAMES:
        raise ValueError("That address is not allowed.")
    try:
        if _is_blocked(ipaddress.ip_address(host)):
            raise ValueError("That address is not allowed.")
    except ValueError as exc:
        if str(exc) == "That address is not allowed.":
            raise
    return endpoint.strip().rstrip("/")


async def refuse_blocked_resolution(endpoint: str) -> None:
    """Names that resolve to a link-local or metadata address are refused (checked when testing)."""
    host = urlsplit(endpoint).hostname or ""
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError as exc:
        raise MediaStoreError("Could not find the storage endpoint. Check its address.") from exc
    for info in infos:
        if _is_blocked(ipaddress.ip_address(info[4][0])):
            raise MediaStoreError("That address is not allowed.")


class S3Store:
    name = "s3"

    def __init__(
        self,
        cfg: S3Config,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: "type[datetime] | None" = None,
    ) -> None:
        self.cfg = cfg
        self._base = urlsplit(cfg.endpoint)
        self._client = httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=False
        )
        self._clock = clock or datetime

    # --- addressing ---------------------------------------------------------------------------

    def _target(self, key: str) -> tuple[str, str, str]:
        """(url, host header, canonical path) for a logical key."""
        full = quote(self.cfg.prefix + check_key(key), safe="/-_.~")
        host = self._base.netloc
        base_path = self._base.path.rstrip("/")
        if self.cfg.path_style:
            path = f"{base_path}/{quote(self.cfg.bucket, safe='')}/{full}"
        else:
            host = f"{self.cfg.bucket}.{self._base.netloc}"
            path = f"{base_path}/{full}"
        return f"{self._base.scheme}://{host}{path}", host, path

    def _signed(
        self, method: str, key: str, payload_hash: str, extra: Mapping[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        url, host, path = self._target(key)
        headers = sigv4_headers(
            method,
            host,
            path,
            "",
            extra or {},
            payload_hash,
            access_key=self.cfg.access_key,
            secret_key=self.cfg.secret_key,
            region=self.cfg.region,
            now=self._clock.now(UTC),
        )
        return url, headers

    @staticmethod
    def _fail(status: int | None) -> MediaStoreError:
        if status in (401, 403):
            return MediaStoreError("The storage refused the access key or secret key.")
        if status == 404:
            return MediaStoreError("The bucket or the file was not found.")
        if status is None:
            return MediaStoreError("Could not reach the storage endpoint.")
        return MediaStoreError(f"The storage answered with an error (HTTP {status}).")

    async def _send(self, request: httpx.Request, op: str) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            record_provider("s3", op, "error", time.perf_counter() - started)
            raise self._fail(None) from exc
        record_provider("s3", op, str(response.status_code), time.perf_counter() - started)
        return response

    # --- operations ---------------------------------------------------------------------------

    async def put(self, key: str, path: Path, content_type: str) -> None:
        data = await asyncio.to_thread(path.read_bytes)
        url, headers = self._signed("PUT", key, hashlib.sha256(data).hexdigest())
        headers["Content-Type"] = content_type
        response = await self._send(
            self._client.build_request("PUT", url, headers=headers, content=data), "put"
        )
        await response.aclose()
        if response.status_code not in (200, 201, 204):
            raise self._fail(response.status_code)

    async def open(self, key: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]:
        extra = {}
        if start or end is not None:
            extra["Range"] = f"bytes={start}-{'' if end is None else end}"
        url, headers = self._signed("GET", key, EMPTY_SHA256, extra)
        response = await self._send(self._client.build_request("GET", url, headers=headers), "get")
        try:
            if response.status_code not in (200, 206):
                raise self._fail(response.status_code)
            async for chunk in response.aiter_bytes(CHUNK):
                yield chunk
        finally:
            await response.aclose()

    async def delete(self, key: str) -> None:
        url, headers = self._signed("DELETE", key, EMPTY_SHA256)
        response = await self._send(
            self._client.build_request("DELETE", url, headers=headers), "delete"
        )
        await response.aclose()
        if response.status_code not in (200, 204, 404):
            raise self._fail(response.status_code)

    async def probe(self) -> None:
        await refuse_blocked_resolution(self.cfg.endpoint)
        key = f"probe/{secrets.token_hex(8)}.txt"
        fd, name = await asyncio.to_thread(tempfile.mkstemp, prefix="iris-probe-")
        tmp = Path(name)
        await asyncio.to_thread(os.close, fd)
        await asyncio.to_thread(tmp.write_bytes, b"iris")
        try:
            await self.put(key, tmp, "text/plain")
            if b"".join([c async for c in self.open(key)]) != b"iris":
                raise MediaStoreError("The storage returned different data than was written.")
            await self.delete(key)
        finally:
            await asyncio.to_thread(tmp.unlink, True)

    async def aclose(self) -> None:
        await self._client.aclose()
