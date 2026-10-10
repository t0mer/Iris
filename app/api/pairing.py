"""Owned, expiring OpenWA drafts; no monitoring until the complete form is saved."""

import asyncio
import base64
import binascii
import hashlib
import json
import re
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.instances import (
    InstanceOut,
    clear_missing_sender,
    instance_out,
    validate_base_url,
    webhook_secret,
)
from app.config import Settings, get_settings
from app.db.models import Instance, Setting, User
from app.deps import get_db
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import admin_user
from app.security.crypto import decrypt, encrypt
from app.settings_store import get_setting

router = APIRouter(prefix="/api/pairing", tags=["pairing"])
DB = Annotated[AsyncSession, Depends(get_db)]
Cfg = Annotated[Settings, Depends(get_settings)]
Owner = Annotated[User, Depends(admin_user)]
PREFIX = "pairing.draft."
COMPLETED_PREFIX = "pairing.completed."
LEASE_SECONDS = 120
MAX_AGE = 1800
QR_SECONDS = 120
_lock = asyncio.Lock()


class PairingIn(BaseModel):
    openwa_base_url: str | None = None
    openwa_api_key: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, max_length=100)


@router.get("/config")
async def pairing_config(cfg: Cfg, user: Owner) -> dict[str, bool]:
    return {"configured": bool(cfg.openwa_url and cfg.openwa_api_key)}


def session_name(name: str | None) -> str:
    if name is None:
        return "iris-draft-" + secrets.token_hex(12)
    name = name.strip()
    if not name:
        raise HTTPException(422, "Enter the phone owner's name before pairing")
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")[:50]
    if len(cleaned) < 3:
        cleaned = "iris-" + hashlib.sha256(name.encode()).hexdigest()[:16]
    return cleaned[:40] + "-" + secrets.token_hex(4)


class PairingComplete(BaseModel):
    kid_name: str | None = Field(default=None, max_length=100)
    role: Literal["child", "parent"] | None = None
    enabled: bool = True


def _decode(row: Setting, cfg: Settings) -> dict[str, Any]:
    return dict(json.loads(decrypt(cfg.key_bytes, row.value)))


async def _save(db: AsyncSession, row: Setting, data: dict[str, Any], cfg: Settings) -> None:
    row.value = encrypt(cfg.key_bytes, json.dumps(data))
    await db.commit()


@asynccontextmanager
async def _client(data: dict[str, Any]) -> AsyncIterator[OpenWAClient]:
    client = OpenWAClient(data["url"], data["key"])
    try:
        yield client
    finally:
        await client.aclose()


def _body(value: Any) -> Any:
    return value.get("data", value) if isinstance(value, dict) else value


async def _owned(
    db: AsyncSession, token: str, user: User, cfg: Settings
) -> tuple[Setting, dict[str, Any]]:
    row = await db.get(Setting, PREFIX + token)
    if row is None:
        raise HTTPException(404, "Pairing draft no longer exists")
    data = _decode(row, cfg)
    if data["owner"] != user.id:
        raise HTTPException(404, "Pairing draft no longer exists")
    return row, data


async def _remove(db: AsyncSession, row: Setting, data: dict[str, Any], cfg: Settings) -> bool:
    """Delete only a randomly named draft owned by this workflow, never a registered phone."""
    async with _client(data) as client:
        session_id = data.get("session_id")
        if not session_id:
            found = _body(
                await client._request("GET", "/api/sessions", params={"name": data["name"]})
            )
            if not isinstance(found, list):
                raise OpenWAError(None, "OpenWA session lookup returned invalid data")
            matches = (
                [s for s in found if s.get("name") == data["name"]]
                if isinstance(found, list)
                else []
            )
            session_id = matches[0]["id"] if len(matches) == 1 else None
            if len(matches) > 1:
                raise HTTPException(409, "Draft session ownership could not be verified")
            if session_id is None and time.time() - data["created"] < LEASE_SECONDS:
                return False  # an ambiguous create response may still commit upstream
        if session_id:
            registered = await db.scalar(
                select(Instance.id).where(
                    Instance.openwa_instance_id == session_id,
                )
            )
            if registered is None:
                try:
                    session = _body(
                        await client._request("GET", f"/api/sessions/{quote(session_id, safe='')}")
                    )
                    if session.get("name") != data["name"]:
                        raise HTTPException(409, "Draft session ownership could not be verified")
                    try:
                        await client._request(
                            "POST", f"/api/sessions/{quote(session_id, safe='')}/logout"
                        )
                    except OpenWAError as exc:
                        if exc.status not in (400, 404):
                            raise
                    await client._request("DELETE", f"/api/sessions/{quote(session_id, safe='')}")
                except OpenWAError as exc:
                    if exc.status != 404:
                        raise
    await db.delete(row)
    await db.commit()
    return True


@router.post("", status_code=201)
async def begin(
    body: PairingIn, db: DB, cfg: Cfg, user: Owner, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    async with _lock:
        count = await db.scalar(
            select(func.count()).select_from(Setting).where(Setting.key.startswith(PREFIX))
        )
        if (count or 0) >= 8:
            raise HTTPException(429, "Finish or cancel another pairing draft first")
        url = cfg.openwa_url or body.openwa_base_url
        key = cfg.openwa_api_key or body.openwa_api_key
        if not url or not key:
            raise HTTPException(
                409, "Configure OPENWA_URL and OPENWA_API_KEY before automatic pairing"
            )
        token = secrets.token_urlsafe(24)
        data = {
            "owner": user.id,
            "url": validate_base_url(url),
            "key": key,
            "name": session_name(body.name),
            "created": time.time(),
            "expires": time.time() + LEASE_SECONDS,
        }
        row = Setting(
            key=PREFIX + token, value=encrypt(cfg.key_bytes, json.dumps(data)), is_secret=True
        )
        db.add(row)
        await db.commit()  # survives a dropped create response or an Iris restart
        try:
            async with _client(data) as client:
                session = _body(
                    await client._request("POST", "/api/sessions", json={"name": data["name"]})
                )
                data["session_id"] = session["id"]
                await _save(db, row, data, cfg)
                await client._request(
                    "POST", f"/api/sessions/{quote(session['id'], safe='')}/start"
                )
        except (OpenWAError, KeyError, TypeError) as exc:
            if (
                not data.get("session_id")
                and isinstance(exc, OpenWAError)
                and exc.status in (400, 401, 403, 409, 422)
            ):
                await db.delete(row)
                await db.commit()
                raise HTTPException(
                    502, "OpenWA rejected pairing. Check its address and API key."
                ) from None
            data["expires"] = 0
            await _save(db, row, data, cfg)
            with suppress(OpenWAError, HTTPException):
                await _remove(db, row, data, cfg)
            # Durable cleanup loop retries failures; no QR or draft token is exposed.
            raise HTTPException(
                502, "OpenWA pairing could not start. Check its connection and API key."
            ) from None
        return {
            "token": token,
            "session_name": data["name"],
            "session_id": data["session_id"],
            "status": "waiting",
            "qr": None,
        }


async def _status(
    db: AsyncSession, row: Setting, data: dict[str, Any], cfg: Settings, refresh: bool = False
) -> dict[str, Any]:
    now = time.time()
    if data["expires"] <= now or now - data["created"] >= MAX_AGE:
        raise HTTPException(410, "Pairing expired. Start a new pairing.")
    data["expires"] = min(now + LEASE_SECONDS, data["created"] + MAX_AGE)
    await _save(db, row, data, cfg)
    sid = quote(data["session_id"], safe="")
    try:
        async with _client(data) as client:
            session = _body(await client._request("GET", f"/api/sessions/{sid}"))
            if session.get("name") != data["name"]:
                raise HTTPException(409, "Draft session ownership could not be verified")
            status = session.get("status", "waiting")
            if status == "ready":
                phone = session.get("phone")
                phone = re.sub(r"\D", "", str(phone).split("@")[0]) if phone else None
                data["phone_number"] = (
                    phone if phone and re.fullmatch(r"[1-9][0-9]{5,14}", phone) else None
                )
                await _save(db, row, data, cfg)
                return {
                    "status": "ready",
                    "qr": None,
                    "session_id": data["session_id"],
                    "phone_number": data["phone_number"],
                    "session_name": data["name"],
                }
            if status in ("authenticating", "initializing"):
                return {"status": status, "qr": None, "session_id": data["session_id"]}
            if refresh or status in ("created", "disconnected", "failed", "action_required"):
                await client._request("POST", f"/api/sessions/{sid}/stop")
                await client._request("POST", f"/api/sessions/{sid}/start")
                data.pop("qr_hash", None)
                data.pop("qr_since", None)
                await _save(db, row, data, cfg)
                return {"status": "waiting", "qr": None, "session_id": data["session_id"]}
            qr_data = _body(await client._request("GET", f"/api/sessions/{sid}/qr"))
            qr = qr_data.get("qrCode") if isinstance(qr_data, dict) else None
            valid_qr = qr is None or isinstance(qr, str)
            if isinstance(qr, str):
                try:
                    image = base64.b64decode(qr.split(",", 1)[-1], validate=True)
                    valid_qr = image.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
                except (ValueError, binascii.Error):
                    valid_qr = False
            if (
                not valid_qr
                or qr is not None
                and (
                    not isinstance(qr, str)
                    or len(qr) > 1_000_000
                    or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", qr)
                )
            ):
                await client._request("POST", f"/api/sessions/{sid}/stop")
                await client._request("POST", f"/api/sessions/{sid}/start")
                data.pop("qr_hash", None)
                data.pop("qr_since", None)
                await _save(db, row, data, cfg)
                return {"status": "waiting", "qr": None, "session_id": data["session_id"]}
            if qr:
                digest = hashlib.sha256(qr.encode()).hexdigest()
                if digest == data.get("qr_hash") and now - data.get("qr_since", now) >= QR_SECONDS:
                    await client._request("POST", f"/api/sessions/{sid}/stop")
                    await client._request("POST", f"/api/sessions/{sid}/start")
                    data.pop("qr_hash", None)
                    data.pop("qr_since", None)
                    await _save(db, row, data, cfg)
                    return {"status": "waiting", "qr": None, "session_id": data["session_id"]}
                if digest != data.get("qr_hash"):
                    data.update(qr_hash=digest, qr_since=now)
                    await _save(db, row, data, cfg)
            return {
                "status": "qr_ready" if qr else "waiting",
                "qr": qr,
                "session_id": data["session_id"],
                "qr_valid_seconds": QR_SECONDS,
            }
    except OpenWAError as exc:
        if exc.status == 400:  # engine has not emitted its next QR yet
            return {"status": "waiting", "qr": None, "session_id": data["session_id"]}
        raise HTTPException(502, "OpenWA is unavailable. No QR is available.") from None


@router.get("/{token}")
async def status(token: str, db: DB, cfg: Cfg, user: Owner, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    async with _lock:
        row, data = await _owned(db, token, user, cfg)
        return await _status(db, row, data, cfg)


@router.post("/{token}/refresh")
async def refresh(token: str, db: DB, cfg: Cfg, user: Owner, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    async with _lock:
        row, data = await _owned(db, token, user, cfg)
        return await _status(db, row, data, cfg, refresh=True)


@router.delete("/{token}", status_code=204)
async def cancel(token: str, db: DB, cfg: Cfg, user: Owner) -> None:
    async with _lock:
        row = await db.get(Setting, PREFIX + token)
        if row is None:
            return
        row, data = await _owned(db, token, user, cfg)
        data["expires"] = 0
        await _save(db, row, data, cfg)
        try:
            await _remove(db, row, data, cfg)
        except OpenWAError:
            raise HTTPException(
                503, "OpenWA is unavailable. Temporary session cleanup will retry automatically."
            ) from None


@router.post("/{token}/complete", status_code=201)
async def complete(token: str, body: PairingComplete, db: DB, cfg: Cfg, user: Owner) -> InstanceOut:
    async with _lock:
        receipt_key = COMPLETED_PREFIX + hashlib.sha256(token.encode()).hexdigest()
        receipt = await db.get(Setting, receipt_key)
        if receipt is not None:
            if receipt.value.get("owner") != user.id:
                raise HTTPException(404, "Pairing request not found")
            if receipt.value.get("expires", 0) > time.time():
                instance = await db.get(Instance, receipt.value["instance_id"])
                if instance is not None:
                    return await instance_out(db, instance, cfg)
        row, data = await _owned(db, token, user, cfg)
        state = await _status(db, row, data, cfg)
        if state["status"] != "ready":
            raise HTTPException(409, "Finish WhatsApp pairing before saving the phone")
        if await db.scalar(
            select(Instance.id).where(
                Instance.openwa_base_url == data["url"],
                Instance.openwa_instance_id == data["session_id"],
            )
        ):
            raise HTTPException(409, "This session is already registered")
        inst = Instance(
            kid_name=(body.kid_name or "").strip() or data["name"],
            phone_number=data.get("phone_number"),
            openwa_base_url=data["url"],
            openwa_instance_id=data["session_id"],
            openwa_api_key_enc=encrypt(cfg.key_bytes, data["key"]),
            webhook_token=secrets.token_urlsafe(32),
            signature_required=True,
            enabled=False,
        )
        if body.role != "parent":
            try:
                async with _client(data) as client:
                    await client.register_webhook(
                        data["session_id"],
                        f"{cfg.webhook_url_base}/webhooks/{inst.webhook_token}",
                        webhook_secret(cfg, inst.webhook_token),
                        retry_count=int(await get_setting(db, "openwa.webhook_attempts")),
                    )
            except OpenWAError:
                raise HTTPException(
                    502, "OpenWA webhook registration failed. The phone has not been saved."
                ) from None
            inst.signature_required = True
            inst.enabled = body.enabled
        await clear_missing_sender(db)
        db.add(inst)
        await db.flush()
        roles = dict(await get_setting(db, "phones.roles"))
        roles[str(inst.id)] = body.role or "child"
        role_row = await db.get(Setting, "phones.roles")
        if role_row is None:
            db.add(Setting(key="phones.roles", value=roles, is_secret=False))
        else:
            role_row.value = roles
        db.add(
            Setting(
                key=receipt_key,
                value={"owner": user.id, "instance_id": inst.id, "expires": time.time() + MAX_AGE},
                is_secret=False,
            )
        )
        await db.delete(row)
        await db.commit()  # phone and ownership transfer are committed together
        return await instance_out(db, inst, cfg)


async def cleanup_once(factory: async_sessionmaker[AsyncSession]) -> None:
    async with _lock, factory() as db:
        cfg = get_settings()
        completed = (
            await db.scalars(select(Setting).where(Setting.key.startswith(COMPLETED_PREFIX)))
        ).all()
        for receipt in completed:
            if receipt.value.get("expires", 0) <= time.time():
                await db.execute(delete(Setting).where(Setting.key == receipt.key))
        await db.commit()
        keys = list(await db.scalars(select(Setting.key).where(Setting.key.startswith(PREFIX))))
        for key in keys:
            row = await db.get(Setting, key)
            if row is None:
                continue
            data = _decode(row, cfg)
            if data["expires"] <= time.time() or time.time() - data["created"] >= MAX_AGE:
                await _remove(db, row, data, cfg)


async def cleanup_loop(
    factory: async_sessionmaker[AsyncSession],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    from app.schedules import schedule_config, tracked

    while True:
        interval = 15
        try:
            async with factory() as db:
                config = await schedule_config(db, "pairing_cleanup")
            interval = config["interval"]
            if config["enabled"]:
                await tracked(factory, "pairing_cleanup", lambda: cleanup_once(factory))
        except Exception:
            logger.exception("pairing cleanup pass failed; retrying")
        await sleep(interval)
