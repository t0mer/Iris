"""Admin auth: argon2 hashing, signed session cookie, login rate limit."""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import User
from app.deps import get_db

COOKIE_NAME = "iris_session"
SESSION_MAX_AGE = 7 * 24 * 3600
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = 15 * 60

_hasher = PasswordHasher()
# Verified against when the username is unknown, so timing doesn't reveal valid usernames.
_DUMMY_HASH = _hasher.hash("iris-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    # Derive a signing key distinct from the encryption key.
    key = hmac.new(settings.key_bytes, b"iris-session-v1", hashlib.sha256).hexdigest()
    return URLSafeTimedSerializer(key, salt="session")


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def user_fingerprint(user: User) -> str:
    return _fingerprint(f"{user.password_hash}:{user.role}:{user.auth_version}")


def make_session_token(settings: Settings, user: User) -> str:
    # Bound to the password hash, so changing the password revokes existing sessions.
    return _serializer(settings).dumps({"uid": user.id, "pv": user_fingerprint(user)})


def read_session_token(settings: Settings, token: str) -> tuple[int, str] | None:
    try:
        data = _serializer(settings).loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    uid, pv = data.get("uid"), data.get("pv")
    return (uid, pv) if isinstance(uid, int) and isinstance(pv, str) else None


class LoginLimiter:
    """In-memory: 5 failures per 15 minutes per IP."""

    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, now: float) -> deque[float]:
        q = self._fails[ip]
        while q and now - q[0] > LOGIN_WINDOW:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        return len(self._prune(ip, time.monotonic())) >= LOGIN_MAX_FAILURES

    def record_failure(self, ip: str) -> float:
        token = time.monotonic()
        self._prune(ip, token).append(token)
        return token

    def release(self, ip: str, token: float) -> None:
        """Remove only this successful attempt's reservation; preserve other failures."""
        q = self._prune(ip, time.monotonic())
        if token in q:
            q.remove(token)

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


async def bootstrap_admin(session: AsyncSession, settings: Settings) -> None:
    """Create the initial admin on first run; env credentials are ignored afterwards."""
    if (await session.execute(select(User.id).limit(1))).first():
        return
    if not settings.admin_username or not settings.admin_password:
        raise RuntimeError("IRIS_ADMIN_USERNAME and IRIS_ADMIN_PASSWORD are required on first run")
    session.add(
        User(username=settings.admin_username, password_hash=hash_password(settings.admin_password))
    )
    await session.commit()


async def current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    parsed = read_session_token(settings, token) if token else None
    user = await db.get(User, parsed[0]) if parsed else None
    if user is None or parsed is None or not hmac.compare_digest(parsed[1], user_fingerprint(user)):
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.scope["audit_actor"] = (user.id, user.username)
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


async def parent_user(user: Annotated[User, Depends(current_user)]) -> User:
    """Parents can act on monitored data; account and system settings remain admin-only."""
    if user.role not in ("admin", "parent"):
        raise HTTPException(status_code=403, detail="Parent or administrator access required")
    return user
