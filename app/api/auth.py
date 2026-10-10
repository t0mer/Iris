"""/api/auth endpoints."""

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Instance, LoginChallenge, Setting, User
from app.deps import get_db
from app.languages import SUPPORTED_LANGUAGES
from app.security.auth import (
    _DUMMY_HASH,
    COOKIE_NAME,
    SESSION_MAX_AGE,
    LoginLimiter,
    current_user,
    hash_password,
    make_session_token,
    user_fingerprint,
    verify_password,
)
from app.security.two_factor import (
    CONTACT_PREFIX,
    ENABLED_KEY,
    available_channels,
    deliver,
    digest,
    load,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = LoginLimiter()
_login_reservations: dict[str, tuple[str, float]] = {}
code_requests = LoginLimiter()
_hash_gate = asyncio.Semaphore(2)
_inflight_logins = 0


class LoginBody(BaseModel):
    username: str = Field(max_length=255)
    password: str = Field(max_length=256)
    channel: Literal["email", "whatsapp"] | None = None


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class LanguageBody(BaseModel):
    language: str = Field(max_length=32)

    @field_validator("language")
    @classmethod
    def supported_language(cls, language: str) -> str:
        if language != "system" and language not in SUPPORTED_LANGUAGES:
            raise ValueError("Unsupported interface language")
        return language


class LearningSharingBody(BaseModel):
    enabled: bool
    acknowledged_policy: Literal["synthetic-only-v1"] | None = None


@router.get("/learning-sharing")
async def learning_sharing(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(Setting, f"internal.learning_sharing.{user.id}")
    enabled = bool(
        row and row.value.get("enabled") is True and row.value.get("policy") == "synthetic-only-v1"
    )
    return {"enabled": enabled, "policy": "synthetic-only-v1", "automatic_upload": False}


@router.patch("/learning-sharing")
async def change_learning_sharing(
    body: LearningSharingBody,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if body.enabled and body.acknowledged_policy != "synthetic-only-v1":
        raise HTTPException(422, "Explicit approval of the sharing policy is required")
    key = f"internal.learning_sharing.{user.id}"
    value = {
        "enabled": body.enabled,
        "policy": "synthetic-only-v1",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    row = await db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    await db.commit()
    return {"enabled": body.enabled, "policy": "synthetic-only-v1", "automatic_upload": False}


def _set_session_cookie(response: Response, settings: Settings, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(settings, user),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=settings.public_base_url.startswith("https://"),
    )


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    ip = _ip(request)
    if limiter.blocked(ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts")
    reservation: float | None = None
    reserved = settings.local_safety_mode
    if reserved:
        if _hash_gate.locked():
            raise HTTPException(status_code=429, detail="Login capacity reached; retry later")
        # Reserve before the first await, closing the concurrent-attempt limiter race.
        reservation = limiter.record_failure(ip)
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if reserved:
        async with _hash_gate:
            ok = await asyncio.to_thread(
                verify_password,
                user.password_hash if user else _DUMMY_HASH,
                body.password,
            )
    else:
        ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not ok:
        if not reserved:
            limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # Correct credentials are not a failed attempt, including failed delivery.
    request.scope["audit_actor"] = (user.id, user.username)
    if reservation is not None:
        limiter.release(ip, reservation)
        reservation = None
    if await load(db, ENABLED_KEY, False):
        channels = await available_channels(db, settings, user)
        if not channels:
            raise HTTPException(403, "Ask your admin to approve your email or WhatsApp number")
        channel = body.channel if body.channel in channels else channels[0]
        request_key = f"{settings.data_dir}:{user.id}"
        if code_requests.blocked(request_key):
            raise HTTPException(
                429, "Too many code requests. Verify the latest code or retry later."
            )
        reservation = code_requests.record_failure(request_key)
        challenge_id = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            await deliver(db, settings, user, channel, code)
        except BaseException:
            code_requests.release(request_key, reservation)
            raise
        await db.execute(
            delete(LoginChallenge).where(LoginChallenge.expires_at <= datetime.now(UTC))
        )
        await db.execute(
            update(LoginChallenge).where(LoginChallenge.user_id == user.id).values(consumed=True)
        )
        db.add(
            LoginChallenge(
                id=challenge_id,
                user_id=user.id,
                fingerprint=user_fingerprint(user),
                code_hash=digest(settings, challenge_id, code),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await db.commit()
        if reservation is not None:
            # The reservation belongs only to this login, never all failures at its IP.
            for previous_id, (_, token) in list(_login_reservations.items()):
                if time.monotonic() - token > 900:
                    _login_reservations.pop(previous_id, None)
            _login_reservations[challenge_id] = (request_key, reservation)
        return {"two_factor_required": True, "challenge_id": challenge_id, "channel": channel}
    if reservation is not None:
        limiter.release(ip, reservation)
    _set_session_cookie(response, settings, user)
    return {"username": user.username}


@router.post("/login")
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    global _inflight_logins
    if not settings.local_safety_mode:
        return await _login(body, request, response, db, settings)
    # Reserve globally before any database/hash await, rather than queueing unlimited hashes.
    if _inflight_logins >= 2:
        raise HTTPException(status_code=429, detail="Login capacity reached; retry later")
    _inflight_logins += 1
    try:
        return await _login(body, request, response, db, settings)
    finally:
        _inflight_logins -= 1


@router.post("/logout")
async def logout(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, bool]:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="strict",
        secure=settings.public_base_url.startswith("https://"),
    )
    return {"ok": True}


@router.get("/me")
async def me(user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    return {"username": user.username, "role": user.role, "id": user.id, "language": user.language}


@router.patch("/language")
async def change_language(
    body: LanguageBody,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    user.language = body.language
    db.add(user)
    await db.commit()
    return {"language": user.language}


@router.post("/password")
async def change_password(
    body: PasswordBody,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    await db.commit()
    # Sessions are bound to the password hash: every other session is now signed out, and this
    # one gets a fresh cookie so the admin who just changed it is not logged out too.
    _set_session_cookie(response, settings, user)
    return {"ok": True}


class VerifyBody(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64)

    @field_validator("code")
    @classmethod
    def clean_code(cls, value: str) -> str:
        value = re.sub(r"[\s\u200b-\u200f\u202a-\u202e\u2066-\u2069]", "", value)
        if not re.fullmatch(r"[0-9]{6}", value):
            raise ValueError("Enter the six-digit verification code")
        return value


@router.get("/options")
async def login_options(
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    from app.settings_store import get_setting

    return {
        "default_channel": await get_setting(db, "auth.default_channel"),
        "two_factor_enabled": bool(await load(db, ENABLED_KEY, False)),
        "secure_login_url": settings.public_base_url
        if settings.public_base_url.startswith("https://")
        else None,
    }


@router.post("/verify")
async def verify_code(
    body: VerifyBody,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    ip = _ip(request)
    now = datetime.now(UTC)
    # Atomic reservation prevents concurrent attempts exceeding the challenge budget.
    result = await db.execute(
        update(LoginChallenge)
        .where(
            LoginChallenge.id == body.challenge_id,
            LoginChallenge.consumed.is_(False),
            LoginChallenge.expires_at > now,
            LoginChallenge.attempts < 5,
        )
        .values(attempts=LoginChallenge.attempts + 1)
    )
    await db.commit()
    challenge = await db.get(LoginChallenge, body.challenge_id)
    user = await db.get(User, challenge.user_id) if challenge else None
    if (
        cast(CursorResult[Any], result).rowcount != 1
        or challenge is None
        or user is None
        or not hmac.compare_digest(challenge.fingerprint, user_fingerprint(user))
        or not hmac.compare_digest(
            challenge.code_hash, digest(settings, body.challenge_id, body.code)
        )
    ):
        limiter.record_failure(ip)
        reason, detail = "incorrect_code", "Invalid verification code. Try again."
        if challenge is None:
            reason, detail = (
                "missing_request",
                "This sign-in request is no longer available. Request a new code.",
            )
        elif user is None or not hmac.compare_digest(challenge.fingerprint, user_fingerprint(user)):
            reason, detail = (
                "account_changed",
                "Your account was updated after this code was sent. Request a new code.",
            )
        elif challenge.consumed:
            reason, detail = (
                "already_used",
                "This code has already been used or replaced. Request a new code.",
            )
        elif challenge.expires_at <= now:
            reason, detail = "expired", "This code has expired. Request a new code."
        elif cast(CursorResult[Any], result).rowcount != 1 and challenge.attempts >= 5:
            reason, detail = "attempt_limit", "Too many attempts for this code. Request a new code."
        logger.warning("2FA verification rejected: reason={}", reason)
        raise HTTPException(401, detail)
    consumed = await db.execute(
        update(LoginChallenge)
        .where(
            LoginChallenge.id == body.challenge_id,
            LoginChallenge.consumed.is_(False),
        )
        .values(consumed=True)
    )
    await db.commit()
    if cast(CursorResult[Any], consumed).rowcount != 1:
        raise HTTPException(401, "Verification code already used")
    reservation = _login_reservations.pop(body.challenge_id, None)
    if reservation is not None:
        code_requests.release(*reservation)
    _set_session_cookie(response, settings, user)
    return {"username": user.username}


@router.get("/phones")
async def watch_phones(
    _: Annotated[User, Depends(current_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> list[dict[str, Any]]:
    from app.settings_store import get_setting

    roles = await get_setting(db, "phones.roles")
    return [
        {
            "id": i.id,
            "kid_name": i.kid_name,
            "role": roles.get(str(i.id), "child"),
        }
        for i in (await db.execute(select(Instance).order_by(Instance.id))).scalars()
    ]


class ConfirmContactBody(BaseModel):
    token: str = Field(min_length=1, max_length=128)


@router.post("/confirm-contact")
async def confirm_contact(
    body: ConfirmContactBody, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    key = CONTACT_PREFIX + hashlib.sha256(body.token.encode()).hexdigest()
    row = await db.get(Setting, key)
    if not row or datetime.fromisoformat(row.value["expires"]) <= datetime.now(UTC):
        raise HTTPException(400, "Approval link is invalid or expired. Request a new one.")
    value = row.value
    if value["channel"] == "telegram":
        from app.alerts.readiness import delivery_readiness
        from app.security.two_factor import save

        readiness = await delivery_readiness(db, "telegram")
        if not any(
            r.user_id == value["user_id"] and r.destination == value["contact"]
            for r in readiness.recipients
        ):
            raise HTTPException(400, "Telegram destination changed. Request a new approval link.")
        claimed = cast(
            CursorResult[Any], await db.execute(delete(Setting).where(Setting.key == key))
        )
        if claimed.rowcount != 1:
            raise HTTPException(400, "Approval link has already been used")
        await save(
            db, f"security.telegram_approved.{value['user_id']}", {"chat_id": value["contact"]}
        )
        await db.commit()
        return {"channel": "telegram"}
    contact_column = User.email if value["channel"] == "email" else User.whatsapp_number
    verification_column = "email_verified" if value["channel"] == "email" else "whatsapp_verified"
    claimed = cast(CursorResult[Any], await db.execute(delete(Setting).where(Setting.key == key)))
    if claimed.rowcount != 1:
        raise HTTPException(400, "Approval link has already been used")
    result = cast(
        CursorResult[Any],
        await db.execute(
            update(User)
            .where(User.id == value["user_id"], contact_column == value["contact"])
            .values(**{verification_column: True})
        ),
    )
    if result.rowcount != 1:
        raise HTTPException(400, "Contact changed. Request a new approval link.")
    await db.commit()
    return {"channel": value["channel"]}
