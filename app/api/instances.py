"""/api/instances: CRUD for the kids' WhatsApp numbers. API keys are write-only."""

import base64
import binascii
import hashlib
import hmac
import ipaddress
import re
import secrets
import time
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Instance, Message, MessageReceipt, Setting, StoredMedia
from app.deps import get_db
from app.openwa.client import OpenWAClient, OpenWAError
from app.security.auth import admin_user
from app.security.crypto import decrypt, encrypt
from app.settings_store import get_setting, set_setting

router = APIRouter(prefix="/api/instances", tags=["instances"], dependencies=[Depends(admin_user)])

DB = Annotated[AsyncSession, Depends(get_db)]
Cfg = Annotated[Settings, Depends(get_settings)]

# Remember only a QR fingerprint, never the image or WhatsApp credentials.
_qr_seen: dict[tuple[int, str], tuple[str, float]] = {}
QR_VALID_SECONDS = 120


def _validated_qr(value: object) -> str | None:
    if value is None:
        return None
    try:
        if (
            not isinstance(value, str)
            or len(value) > 1_000_000
            or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", value)
        ):
            raise ValueError
        image = base64.b64decode(value.split(",", 1)[1], validate=True)
        if not image.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
            raise ValueError
    except (ValueError, binascii.Error):
        raise HTTPException(502, "OpenWA returned an invalid QR. Request a new code.") from None
    return value


def _repair_error(instance_id: int, exc: OpenWAError) -> HTTPException:
    cause = type(exc.__cause__).__name__ if exc.__cause__ else "HTTPError"
    logger.warning(
        "OpenWA repair failed: instance={} status={} cause={}", instance_id, exc.status, cause
    )
    if cause in ("ReadTimeout", "ConnectTimeout", "PoolTimeout", "WriteTimeout"):
        return HTTPException(
            502,
            "OpenWA did not respond in time. Check the OpenWA service and retry. "
            "The existing phone has not been removed.",
        )
    if exc.status in (401, 403):
        return HTTPException(
            502,
            "OpenWA rejected the API key. Check the saved sender credentials. "
            "The existing phone has not been removed.",
        )
    return HTTPException(502, "OpenWA is unavailable. The existing phone has not been removed.")


@router.get("/{instance_id}/qr")
async def qr_code(instance_id: int, db: DB, settings: Cfg, response: Response) -> dict[str, object]:
    """Read the provider QR directly for the authenticated, embedded Iris viewer."""
    response.headers["Cache-Control"] = "no-store"
    inst = await _get(db, instance_id)
    if not inst.openwa_api_key_enc:
        raise HTTPException(422, "OpenWA API key is not set")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    try:
        value = await client._request(
            "GET", f"/api/sessions/{quote(inst.openwa_instance_id, safe='')}/qr"
        )
        body = value.get("data", value) if isinstance(value, dict) else {}
        qr = _validated_qr(body.get("qrCode") if isinstance(body, dict) else None)
        if not qr:
            return {"status": "waiting", "qr": None}
        now = time.monotonic()
        key = (instance_id, inst.openwa_instance_id)
        digest = hashlib.sha256(qr.encode()).hexdigest()
        previous = _qr_seen.get(key)
        if previous is None or previous[0] != digest:
            _qr_seen[key] = (digest, now)
        elif now - previous[1] >= QR_VALID_SECONDS:
            return {"status": "expired", "qr": None}
        return {"status": "qr_ready", "qr": qr}
    except OpenWAError as exc:
        if exc.status == 400:
            return {"status": "waiting", "qr": None}
        if exc.status == 404:
            raise HTTPException(
                409, "The OpenWA session no longer exists. Add a new phone connection."
            ) from None
        raise _repair_error(instance_id, exc) from None
    finally:
        await client.aclose()


@router.post("/{instance_id}/qr/refresh")
async def refresh_qr(
    instance_id: int, db: DB, settings: Cfg, response: Response
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    inst = await _get(db, instance_id)
    if not inst.openwa_api_key_enc:
        raise HTTPException(422, "OpenWA API key is not set")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    sid = quote(inst.openwa_instance_id, safe="")
    try:
        value = await client._request("GET", f"/api/sessions/{sid}")
        body = value.get("data", value) if isinstance(value, dict) else {}
        status = str(body.get("status", "unknown")) if isinstance(body, dict) else "unknown"
        if status == "ready":
            return {"status": "ready", "qr": None}
        if status in ("authenticating", "initializing"):
            return {"status": status, "qr": None}
        key = (instance_id, inst.openwa_instance_id)
        if key in _qr_seen:
            _qr_seen[key] = (_qr_seen[key][0], time.monotonic() - QR_VALID_SECONDS)
        await client._request("POST", f"/api/sessions/{sid}/stop")
        await client._request("POST", f"/api/sessions/{sid}/start")
        return {"status": "waiting", "qr": None}
    except OpenWAError as exc:
        raise _repair_error(instance_id, exc) from None
    finally:
        await client.aclose()


def webhook_secret(settings: Settings, token: str) -> str:
    """Per-instance HMAC secret for OpenWA's X-OpenWA-Signature, derived (not stored)."""
    return hmac.new(settings.key_bytes, b"webhook:" + token.encode(), hashlib.sha256).hexdigest()


def validate_base_url(url: str) -> str:
    """http(s) only, with a host. Link-local/metadata addresses are never valid OpenWA targets."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=422, detail="OpenWA base URL must be http(s) with a host")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_link_local or ip.is_unspecified or ip.is_multicast):
        raise HTTPException(status_code=422, detail="OpenWA base URL address is not allowed")
    return url.strip().rstrip("/")


class InstanceIn(BaseModel):
    role: Literal["child", "parent"] | None = None
    kid_name: str = Field(min_length=1)
    phone_number: str | None = None
    openwa_base_url: str = Field(min_length=1)
    openwa_instance_id: str = Field(min_length=1)
    openwa_api_key: str | None = None
    enabled: bool = True
    verify_openwa: bool = False


class InstancePatch(BaseModel):
    role: Literal["child", "parent"] | None = None
    kid_name: str | None = Field(default=None, min_length=1)
    phone_number: str | None = None
    openwa_base_url: str | None = None
    openwa_api_key: str | None = None
    openwa_instance_id: str | None = Field(default=None, min_length=1)
    session_name: str | None = Field(default=None, max_length=100)
    verify_openwa: bool = False
    enabled: bool | None = None


class InstanceOut(BaseModel):
    monitoring_status: str = "unchecked"
    monitoring_error: str | None = None
    connection_status: str = "unknown"
    connection_checked_at: datetime | None = None
    session_name: str | None = None
    role: Literal["child", "parent"] = "child"
    id: int
    kid_name: str
    phone_number: str | None
    openwa_base_url: str
    openwa_instance_id: str
    api_key_set: bool
    enabled: bool
    webhook_url: str
    last_webhook_at: datetime | None
    created_at: datetime


def to_out(
    i: Instance, settings: Settings, role: Literal["child", "parent"] = "child"
) -> InstanceOut:
    return InstanceOut(
        id=i.id,
        kid_name=i.kid_name,
        phone_number=i.phone_number,
        openwa_base_url=i.openwa_base_url,
        openwa_instance_id=i.openwa_instance_id,
        api_key_set=bool(i.openwa_api_key_enc),
        enabled=i.enabled,
        webhook_url=f"{settings.webhook_url_base}/webhooks/{i.webhook_token}",
        last_webhook_at=i.last_webhook_at,
        created_at=i.created_at,
        role=role,
    )


async def instance_out(db: AsyncSession, instance: Instance, settings: Settings) -> InstanceOut:
    roles = await get_setting(db, "phones.roles")
    role = roles.get(str(instance.id))
    if role is None:
        role = "child"  # preserve existing monitored instances until explicitly assigned a role
    result = to_out(instance, settings, "parent" if role == "parent" else "child")
    names = await get_setting(db, "phones.session_names")
    result.session_name = names.get(str(instance.id))
    from app.monitoring import session_details

    detail = session_details.get(instance.id)
    if detail:
        result.connection_status, result.connection_checked_at = detail
    monitoring = await db.get(Setting, f"internal.webhook_status.{instance.id}")
    if monitoring:
        result.monitoring_status = str(monitoring.value.get("status", "unchecked"))
        result.monitoring_error = monitoring.value.get("error")
    return result


async def save_role(db: AsyncSession, instance: Instance, role: str | None) -> None:
    if role is not None:
        roles = dict(await get_setting(db, "phones.roles"))
        roles[str(instance.id)] = role
        await set_setting(db, "phones.roles", roles)


async def _get(db: AsyncSession, instance_id: int) -> Instance:
    inst = await db.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return inst


@router.get("")
async def list_instances(db: DB, settings: Cfg) -> list[InstanceOut]:
    rows = (await db.execute(select(Instance).order_by(Instance.id))).scalars().all()
    return [await instance_out(db, i, settings) for i in rows]


async def clear_missing_sender(db: AsyncSession) -> None:
    sender_id = await get_setting(db, "alerts.sender_instance_id")
    if sender_id and await db.get(Instance, sender_id) is None:
        await set_setting(db, "alerts.sender_instance_id", None)


@router.post("", status_code=201)
async def create_instance(body: InstanceIn, db: DB, settings: Cfg) -> InstanceOut:
    base_url = validate_base_url(body.openwa_base_url)
    phone_number = body.phone_number
    if body.verify_openwa:
        if not body.openwa_api_key:
            raise HTTPException(422, "Enter an OpenWA API key before adding this phone")
        client = OpenWAClient(base_url, body.openwa_api_key)
        try:
            result = await client._request(
                "GET", f"/api/sessions/{quote(body.openwa_instance_id, safe='')}"
            )
            session = result.get("data", result) if isinstance(result, dict) else None
            if not isinstance(session, dict) or session.get("id") != body.openwa_instance_id:
                raise HTTPException(
                    502, "OpenWA returned an invalid session. The phone was not added."
                )
            supplied_phone = session.get("phone")
            if supplied_phone:
                phone_number = str(supplied_phone).split("@")[0].lstrip("+")
        except OpenWAError as exc:
            detail = (
                "OpenWA API key was rejected"
                if exc.status in (401, 403)
                else "OpenWA session could not be verified"
            )
            raise HTTPException(
                502,
                detail + ". The phone was not added; check the address, session ID and API key.",
            ) from None
        finally:
            await client.aclose()
    inst = Instance(
        kid_name=body.kid_name,
        phone_number=phone_number,
        openwa_base_url=base_url,
        openwa_instance_id=body.openwa_instance_id,
        openwa_api_key_enc=encrypt(settings.key_bytes, body.openwa_api_key)
        if body.openwa_api_key
        else None,
        webhook_token=secrets.token_urlsafe(32),
        signature_required=True,
        enabled=False if body.role == "parent" else body.enabled,
    )
    await clear_missing_sender(db)
    db.add(inst)
    await db.commit()
    await save_role(db, inst, body.role)
    if body.role != "parent":
        await save_webhook_status(
            db,
            inst.id,
            "failed",
            "Register the signed webhook in OpenWA before monitoring can receive messages",
        )
    return await instance_out(db, inst, settings)


@router.get("/{instance_id}")
async def get_instance(instance_id: int, db: DB, settings: Cfg) -> InstanceOut:
    return await instance_out(db, await _get(db, instance_id), settings)


@router.patch("/{instance_id}")
async def update_instance(
    instance_id: int, body: InstancePatch, db: DB, settings: Cfg
) -> InstanceOut:
    inst = await _get(db, instance_id)
    data = body.model_dump(exclude_unset=True)
    role = data.pop("role", None)
    verify = data.pop("verify_openwa", False)
    session_name_supplied = "session_name" in data
    session_name = data.pop("session_name", None)
    current_role = (await instance_out(db, inst, settings)).role
    if (role or current_role) == "parent":
        if data.get("enabled") is True:
            raise HTTPException(
                status_code=422, detail="Parent sender connections are not monitored"
            )
        data["enabled"] = False
    key = data.pop("openwa_api_key", None)
    if key:  # empty/absent means "leave unchanged": secrets are write-only in the API
        inst.openwa_api_key_enc = encrypt(settings.key_bytes, key)
    if data.get("openwa_base_url"):
        new_url = validate_base_url(data["openwa_base_url"])
        if new_url != inst.openwa_base_url and not key:
            # The stored key must never be sent to a different host without re-entering it.
            raise HTTPException(
                status_code=422, detail="Re-enter the API key when changing the base URL"
            )
        data["openwa_base_url"] = new_url
    if verify:
        effective_key = key or (
            decrypt(settings.key_bytes, inst.openwa_api_key_enc)
            if inst.openwa_api_key_enc
            else None
        )
        if not effective_key:
            raise HTTPException(422, "OpenWA API key is not set")
        client = OpenWAClient(data.get("openwa_base_url") or inst.openwa_base_url, effective_key)
        try:
            result = await client._request(
                "GET",
                "/api/sessions/"
                + quote(data.get("openwa_instance_id") or inst.openwa_instance_id, safe=""),
            )
            session = result.get("data", result) if isinstance(result, dict) else None
            if not isinstance(session, dict) or session.get("id") != (
                data.get("openwa_instance_id") or inst.openwa_instance_id
            ):
                raise HTTPException(
                    502, "OpenWA returned an invalid session. Changes were not saved."
                )
        except OpenWAError:
            raise HTTPException(
                502,
                "OpenWA connection could not be verified. Changes were not saved; "
                "check the address, session ID and key.",
            ) from None
        finally:
            await client.aclose()
    for field, value in data.items():
        if value is not None or field == "phone_number":
            setattr(inst, field, value)
    await db.commit()
    await save_role(db, inst, role)
    if session_name_supplied:
        names = dict(await get_setting(db, "phones.session_names"))
        if session_name and session_name.strip():
            names[str(inst.id)] = session_name.strip()
        else:
            names.pop(str(inst.id), None)
        await set_setting(db, "phones.session_names", names)
    return await instance_out(db, inst, settings)


async def _remove_openwa(
    inst: Instance,
    db: AsyncSession,
    settings: Settings,
    stage: Literal["all", "deactivate", "delete"],
) -> None:
    shared = await db.scalar(
        select(Instance.id).where(
            Instance.id != inst.id,
            Instance.openwa_instance_id == inst.openwa_instance_id,
        )
    )
    if shared is not None:
        raise HTTPException(
            409, "Another Iris phone uses this OpenWA session. Remove that reference first."
        )
    if not inst.openwa_api_key_enc:
        raise HTTPException(422, "OpenWA API key is not set. The phone has not been removed.")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    sid = quote(inst.openwa_instance_id, safe="")
    try:
        if stage in ("all", "deactivate"):
            try:
                await client._request("POST", f"/api/sessions/{sid}/logout")
            except OpenWAError as exc:
                if exc.status not in (400, 404):
                    raise
        if stage in ("all", "delete"):
            try:
                await client._request("DELETE", f"/api/sessions/{sid}")
            except OpenWAError as exc:
                if exc.status != 404:
                    raise
    except OpenWAError:
        raise HTTPException(
            502,
            "OpenWA session removal failed. The Iris phone has been kept; check OpenWA and retry.",
        ) from None
    finally:
        await client.aclose()


@router.post("/{instance_id}/remove-openwa", status_code=204)
async def remove_openwa_stage(
    instance_id: int, stage: Literal["deactivate", "delete"], db: DB, settings: Cfg
) -> None:
    await _remove_openwa(await _get(db, instance_id), db, settings, stage)


@router.delete("/{instance_id}", status_code=204)
async def delete_instance(
    instance_id: int,
    db: DB,
    settings: Cfg,
    delete_openwa: bool = False,
    delete_messages: bool = False,
) -> None:
    inst = await _get(db, instance_id)
    if delete_messages:
        roles = await get_setting(db, "phones.roles")
        if (
            roles.get(str(instance_id)) == "parent"
            or await get_setting(db, "alerts.sender_instance_id") == instance_id
        ):
            raise HTTPException(
                422, "Deleting messages is not available for alert sender connections"
            )
        # Shared messages belong to other connected phones too; delete only exclusive ones.
        others = select(MessageReceipt.message_id).where(MessageReceipt.instance_id != instance_id)
        ids = list(
            (
                await db.execute(
                    select(MessageReceipt.message_id)
                    .join(Message, Message.id == MessageReceipt.message_id)
                    .where(
                        Message.from_me.is_(False),
                        MessageReceipt.instance_id == instance_id,
                        MessageReceipt.message_id.not_in(others),
                    )
                )
            ).scalars()
        )
        if ids:
            await db.execute(
                update(StoredMedia).where(StoredMedia.message_id.in_(ids)).values(purge=True)
            )
            await db.execute(delete(Message).where(Message.id.in_(ids)))
    if delete_openwa:
        await _remove_openwa(inst, db, settings, "all")
    if await get_setting(db, "alerts.sender_instance_id") == instance_id:
        await set_setting(db, "alerts.sender_instance_id", None)
    await db.delete(inst)
    await db.commit()
    roles = dict(await get_setting(db, "phones.roles"))
    roles.pop(str(instance_id), None)
    assignments = await get_setting(db, "alerts.recipient_children")
    await set_setting(
        db,
        "alerts.recipient_children",
        {
            parent: [child for child in children if child != instance_id]
            for parent, children in assignments.items()
        },
    )
    names = dict(await get_setting(db, "phones.session_names"))
    names.pop(str(instance_id), None)
    await set_setting(db, "phones.session_names", names)
    await set_setting(db, "phones.roles", roles, settings.key_bytes)


@router.post("/{instance_id}/re-pair")
async def re_pair(instance_id: int, db: DB, settings: Cfg, response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    inst = await _get(db, instance_id)
    if not inst.openwa_api_key_enc:
        raise HTTPException(422, "OpenWA API key is not set")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    sid = quote(inst.openwa_instance_id, safe="")
    try:
        value = await client._request("GET", f"/api/sessions/{sid}")
        session = value.get("data", value) if isinstance(value, dict) else {}
        if not isinstance(session, dict):
            raise HTTPException(502, "OpenWA returned an invalid session")
        status = str(session.get("status", "unknown"))
        from datetime import UTC

        from app.monitoring import session_details, states

        session_details[inst.id] = (status, datetime.now(UTC))
        states[inst.id] = status == "ready"
        if status == "ready":
            phone = session.get("phone")
            if phone:
                number = str(phone).split("@")[0].lstrip("+")
                if re.fullmatch(r"[1-9][0-9]{5,14}", number) and inst.phone_number != number:
                    inst.phone_number = number
                    await db.commit()
            return {"status": "ready", "qr": None}
        if status in ("created", "disconnected", "failed", "action_required"):
            await client._request("POST", f"/api/sessions/{sid}/start")
            return {"status": "initializing", "qr": None}
        if status in ("initializing", "authenticating"):
            return {"status": status, "qr": None}
        value = await client._request("GET", f"/api/sessions/{sid}/qr")
        body = value.get("data", value) if isinstance(value, dict) else {}
        qr = body.get("qrCode") if isinstance(body, dict) else None
        if qr is not None:
            try:
                if (
                    not isinstance(qr, str)
                    or len(qr) > 1_000_000
                    or not re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=]+", qr)
                ):
                    raise ValueError
                image = base64.b64decode(qr.split(",", 1)[1], validate=True)
                if not image.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
                    raise ValueError
            except (ValueError, binascii.Error):
                raise HTTPException(
                    502, "OpenWA returned an invalid QR. Refresh and retry."
                ) from None
        return {"status": "qr_ready" if qr else "waiting", "qr": qr}
    except OpenWAError as exc:
        if exc.status == 400:
            return {"status": "waiting", "qr": None}
        if exc.status == 404:
            raise HTTPException(
                409, "The OpenWA session no longer exists. Add a new phone connection."
            ) from None
        raise _repair_error(instance_id, exc) from None
    finally:
        await client.aclose()


@router.post("/{instance_id}/check-session")
async def check_session(instance_id: int, db: DB, settings: Cfg) -> InstanceOut:
    from app.monitoring import probe_instance

    instance = await _get(db, instance_id)
    await probe_instance(instance, settings.key_bytes)
    return await instance_out(db, instance, settings)


@router.post("/{instance_id}/rotate-token")
async def rotate_token(instance_id: int, db: DB, settings: Cfg) -> InstanceOut:
    inst = await _get(db, instance_id)
    inst.webhook_token = secrets.token_urlsafe(32)  # the old URL stops working immediately
    inst.signature_required = True  # fail closed until the new secret is registered
    await save_webhook_status(
        db, inst.id, "failed", "Webhook token rotated; register the webhook again"
    )
    return await instance_out(db, inst, settings)


async def save_webhook_status(
    db: AsyncSession, instance_id: int, status: str, error: str | None
) -> None:
    key = f"internal.webhook_status.{instance_id}"
    row = await db.get(Setting, key)
    value = {"status": status, "error": error}
    if row is None:
        db.add(Setting(key=key, value=value, is_secret=False))
    else:
        row.value = value
    await db.commit()


@router.post("/{instance_id}/register-webhook")
async def register_webhook(instance_id: int, db: DB, settings: Cfg) -> dict[str, str]:
    inst = await _get(db, instance_id)
    if not inst.openwa_api_key_enc:
        raise HTTPException(status_code=422, detail="OpenWA API key is not set")
    client = OpenWAClient(
        inst.openwa_base_url, decrypt(settings.key_bytes, inst.openwa_api_key_enc)
    )
    try:
        webhook_id = await client.register_webhook(
            inst.openwa_instance_id,
            f"{settings.webhook_url_base}/webhooks/{inst.webhook_token}",
            webhook_secret(settings, inst.webhook_token),
            retry_count=int(await get_setting(db, "openwa.webhook_attempts")),
        )
    except OpenWAError as exc:
        hint = ""
        if exc.status == 400 and "not allowed" in exc.message.lower():
            hint = (
                " (WhatsApp pairing is separate. Set an allowed, reachable OpenWA webhook "
                "base URL in Settings > Alerts, or allow that destination in OpenWA "
                "SSRF_ALLOWED_HOSTS.)"
            )
        error = f"OpenWA: {exc.message}{hint}"
        await save_webhook_status(db, inst.id, "failed", error)
        raise HTTPException(status_code=502, detail=error) from exc
    finally:
        await client.aclose()
    inst.signature_required = True
    await save_webhook_status(db, inst.id, "registered", None)
    return {"webhook_id": webhook_id}
