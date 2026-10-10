"""Container-only emergency reset; deliberately has no HTTP endpoint."""

import argparse
import asyncio
import getpass
import hmac
import secrets
import sys
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.engine import make_engine, make_session_factory
from app.db.models import LoginChallenge, Setting, User
from app.security.two_factor import CONTACT_PREFIX, ENABLED_KEY, save


async def recover(db: AsyncSession, cfg: Settings, username: str, supplied_key: str) -> None:
    if not cfg.two_factor_recovery_key or len(cfg.two_factor_recovery_key) < 32:
        raise ValueError("Configure IRIS_TWO_FACTOR_RECOVERY_KEY with at least 32 characters")
    if not hmac.compare_digest(cfg.two_factor_recovery_key.encode(), supplied_key.encode()):
        raise ValueError("Recovery key is incorrect")
    admin = await db.scalar(select(User).where(User.username == username, User.role == "admin"))
    if admin is None:
        raise ValueError("Admin account not found")
    await save(db, ENABLED_KEY, False)
    await db.execute(update(User).values(auth_version=User.auth_version + 1))
    await db.execute(delete(LoginChallenge))
    await db.execute(delete(Setting).where(Setting.key.startswith(CONTACT_PREFIX)))
    await save(
        db,
        "security.recovery_audit." + secrets.token_hex(16),
        {
            "admin_id": admin.id,
            "at": datetime.now(UTC).isoformat(),
            "method": "docker_cli",
        },
    )
    await db.commit()


async def main(username: str, supplied_key: str) -> None:
    engine = make_engine()
    try:
        async with make_session_factory(engine)() as db:
            await recover(db, get_settings(), username, supplied_key)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emergency 2FA reset inside the Iris container")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(1, "Run recovery in an interactive Docker console (docker exec -it).\n")
    try:
        asyncio.run(main(args.username, getpass.getpass("Docker recovery key: ")))
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    print(
        "2FA reset for recovery; existing sessions and login challenges revoked. "
        "Restart Iris (docker restart iris) to clear any in-memory login lockout, then "
        "sign in through HTTPS with your password, repair delivery and re-enable 2FA."
    )
