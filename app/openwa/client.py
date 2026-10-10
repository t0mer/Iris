"""Thin OpenWA REST client (X-API-Key auth). Keep all OpenWA endpoint shapes here."""

import asyncio
import base64
import binascii
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.metrics import record_provider

# Cloudflare in front of OpenWA rejects default library User-Agents.
_UA = "iris/1.0"
_TIMEOUT = httpx.Timeout(20.0)
WEBHOOK_EVENTS = ["message.received", "message.sent", "message.edited", "message.revoked"]


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

    async def session_ready(self, session_id: str) -> bool:
        data = await self._request("GET", f"/api/sessions/{quote(session_id, safe='')}")
        body = data.get("data", data) if isinstance(data, dict) else {}
        return isinstance(body, dict) and str(body.get("status", "")).lower() == "ready"

    async def register_webhook(
        self, session_id: str, url: str, secret: str, retry_count: int = 3
    ) -> str:
        """Subscribe the session's webhook for `url` to Iris's events and return its id.

        A webhook already pointing at `url` is updated (its existing events are kept), so running
        this again never creates a duplicate that would deliver every event twice.
        """
        base = f"/api/sessions/{quote(session_id, safe='')}/webhooks"
        listed = await self._request("GET", base)
        items = listed.get("data", listed) if isinstance(listed, dict) else listed
        existing = (
            next(
                (w for w in items if isinstance(w, dict) and w.get("url") == url),
                None,
            )
            if isinstance(items, list)
            else None
        )
        if existing is not None and existing.get("id"):
            have = existing.get("events")
            events = sorted({*WEBHOOK_EVENTS, *(have if isinstance(have, list) else [])})
            await self._request(
                "PUT",
                f"{base}/{quote(str(existing['id']), safe='')}",
                json={"events": events, "secret": secret, "retryCount": retry_count},
            )
            return str(existing["id"])
        data = await self._request(
            "POST",
            base,
            json={
                "url": url,
                "events": WEBHOOK_EVENTS,
                "secret": secret,
                "retryCount": retry_count,
            },
        )
        body = data.get("data", data) if isinstance(data, dict) else {}
        return str(body.get("id", ""))

    async def set_webhook_retries(self, session_id: str, url: str, attempts: int) -> int:
        base = f"/api/sessions/{quote(session_id, safe='')}/webhooks"
        data = await self._request("GET", base)
        rows = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise OpenWAError(502, "Invalid webhook list")
        changed = 0
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("url") == url
                and row.get("id")
                and row.get("retryCount") != attempts
            ):
                await self._request(
                    "PUT", f"{base}/{quote(str(row['id']), safe='')}", json={"retryCount": attempts}
                )
                changed += 1
        return changed

    async def stored_messages(
        self, session_id: str, after: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": 100, "inlineMedia": "false"}
        if after:
            params["after"] = after
        data = await self._request(
            "GET", f"/api/sessions/{quote(session_id, safe='')}/messages", params=params
        )
        rows = data.get("messages") if isinstance(data, dict) else None
        if (
            not isinstance(rows, list)
            or len(rows) > 100
            or any(not isinstance(r, dict) for r in rows)
        ):
            raise OpenWAError(502, "Invalid stored-message page")
        return rows

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

    async def recover_media(
        self, session_id: str, chat_id: str, message_ref: str, dest: Path, max_bytes: int
    ) -> str:
        """Recover only the exact message from a bounded recent-history request.

        No external media URL is followed, and no other message is written to disk.
        OpenWA caps the history media budget at 25 MB by default.
        """
        path = (
            f"/api/sessions/{quote(session_id, safe='')}/messages/{quote(chat_id, safe='')}/history"
        )
        ceiling = min(max_bytes, 25 * 1024 * 1024)
        body_limit = 36 * 1024 * 1024
        try:
            async with asyncio.timeout(65):
                async with self._client.stream(
                    "GET", path, params={"limit": 10, "includeMedia": "true"}, timeout=65
                ) as response:
                    if response.status_code >= 400:
                        raise OpenWAError(response.status_code, "Media recovery unavailable")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > body_limit:
                            raise MediaTooLarge(len(body) + len(chunk))
                        body.extend(chunk)
            rows = json.loads(body)
            if not isinstance(rows, list) or len(rows) > 10:
                raise OpenWAError(502, "Invalid media recovery response")
            for row in rows:
                if not isinstance(row, dict) or row.get("id") != message_ref:
                    continue
                media = row.get("media")
                if not isinstance(media, dict) or media.get("omitted"):
                    break
                data, mimetype = media.get("data"), media.get("mimetype")
                if not isinstance(data, str) or not isinstance(mimetype, str) or not data:
                    break
                if len(data) > ((ceiling + 2) // 3) * 4:
                    raise MediaTooLarge(len(data) * 3 // 4)
                decoded = base64.b64decode(data, validate=True)
                if len(decoded) > ceiling:
                    raise MediaTooLarge(len(decoded))
                await asyncio.to_thread(dest.write_bytes, decoded)
                return mimetype
            raise OpenWAError(404, "Original media is no longer available")
        except (httpx.HTTPError, TimeoutError) as exc:
            raise OpenWAError(None, "Media recovery timed out or connection failed") from exc
        except (ValueError, binascii.Error) as exc:
            raise OpenWAError(502, "Invalid media recovery response") from exc
