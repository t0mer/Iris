"""Thin OpenWA REST client (X-API-Key auth). Keep all OpenWA endpoint shapes here."""

import asyncio
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.metrics import record_provider

# Cloudflare in front of OpenWA rejects default library User-Agents.
_UA = "iris/1.0"
_TIMEOUT = httpx.Timeout(20.0)
WEBHOOK_EVENTS = ["message.received", "message.sent"]


class OpenWAError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class MediaTooLarge(Exception):
    def __init__(self, size: int) -> None:
        super().__init__(f"media is {size} bytes")
        self.size = size


class OpenWAClient:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key, "User-Agent": _UA},
            timeout=_TIMEOUT,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw: Any) -> Any:
        endpoint = path.rsplit("/", 1)[-1] if path.endswith(("send-text", "webhooks")) else "other"
        started = time.perf_counter()
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            record_provider("openwa", endpoint, "error", time.perf_counter() - started)
            raise OpenWAError(None, f"OpenWA unreachable: {exc.__class__.__name__}") from exc
        record_provider("openwa", endpoint, str(r.status_code), time.perf_counter() - started)
        if r.status_code >= 400:
            # Only a plain "message" string is surfaced, never raw upstream bodies.
            detail = f"HTTP {r.status_code}"
            try:
                body = r.json()
                if isinstance(body, dict) and isinstance(body.get("message"), str):
                    detail = body["message"][:200]
            except ValueError:
                pass
            raise OpenWAError(r.status_code, detail)
        return r.json() if r.content else None

    async def register_webhook(self, session_id: str, url: str, secret: str) -> str:
        """Create a webhook for the session and return its id."""
        data = await self._request(
            "POST",
            f"/api/sessions/{quote(session_id, safe='')}/webhooks",
            json={"url": url, "events": WEBHOOK_EVENTS, "secret": secret, "retryCount": 3},
        )
        body = data.get("data", data) if isinstance(data, dict) else {}
        return str(body.get("id", ""))

    async def get_group_name(self, session_id: str, group_id: str) -> str | None:
        """The group's subject from `GET /api/sessions/{id}/groups/{groupId}` (None if unnamed)."""
        data = await self._request(
            "GET", f"/api/sessions/{quote(session_id, safe='')}/groups/{quote(group_id, safe='')}"
        )
        body = data.get("data", data) if isinstance(data, dict) else {}
        name = body.get("name") if isinstance(body, dict) else None
        return name.strip() or None if isinstance(name, str) else None

    async def send_text(self, session_id: str, chat_id: str, text: str) -> None:
        await self._request(
            "POST",
            f"/api/sessions/{quote(session_id, safe='')}/messages/send-text",
            json={"chatId": chat_id, "text": text},
        )

    async def download_media(
        self, session_id: str, chat_id: str, message_ref: str, dest: Path, max_bytes: int
    ) -> str:
        """Stream a message's media to `dest` and return the real Content-Type.

        Raises MediaTooLarge past `max_bytes` (the partial file is removed) and OpenWAError
        otherwise. The webhook's mimetype can be wrong; the response header is authoritative.
        """
        path = (
            f"/api/sessions/{quote(session_id, safe='')}/messages/"
            f"{quote(chat_id, safe='')}/{quote(message_ref, safe='')}/media"
        )
        started = time.perf_counter()
        try:
            async with self._client.stream("GET", path) as r:
                record_provider(
                    "openwa", "media", str(r.status_code), time.perf_counter() - started
                )
                if r.status_code >= 400:
                    raise OpenWAError(r.status_code, f"HTTP {r.status_code}")
                declared = r.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise MediaTooLarge(int(declared))
                size = 0
                with dest.open("wb") as fh:
                    async for chunk in r.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise MediaTooLarge(size)
                        await asyncio.to_thread(fh.write, chunk)
                return str(r.headers.get("content-type", "application/octet-stream"))
        except httpx.HTTPError as exc:
            raise OpenWAError(None, f"OpenWA unreachable: {exc.__class__.__name__}") from exc
        except MediaTooLarge:
            await asyncio.to_thread(dest.unlink, True)
            raise
