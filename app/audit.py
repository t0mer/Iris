"""Record committed changes in the request that caused them; never retain credentials."""

import json
from contextvars import ContextVar
from datetime import datetime
from typing import Any, cast

from loguru import logger
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import ORMExecuteState, Session
from starlette.requests import Request

from app.config import get_settings
from app.db.models import AuditLog, User
from app.security.auth import COOKIE_NAME, read_session_token, user_fingerprint

_context: ContextVar[list[dict[str, Any]] | None] = ContextVar("audit_changes", default=None)
_installed = False
_SECRET_WORDS = (
    "password",
    "secret",
    "token",
    "api_key",
    "fingerprint",
    "code_hash",
    "authorization",
    "cookie",
)
_SAFE_MODELS = {
    "User",
    "Instance",
    "Setting",
    "Message",
    "Alert",
    "AlertView",
    "ReviewFeedback",
    "LearningExample",
    "ReviewResponse",
    "ReviewDataIssue",
    "SkippedGroup",
    "StoredMedia",
    "Job",
}
_CONTENT = {
    "text",
    "transcript",
    "quote",
    "media",
    "diagnostics",
    "payload",
    "webhook_token",
    "explanation",
}


def safe_value(field: str, value: Any, secret: bool = False) -> Any:
    if secret or any(word in field.lower() for word in _SECRET_WORDS):
        return "[set]" if value else "[empty]"
    if field in _CONTENT:
        return "[present]" if value else "[empty]"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): safe_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_value(field, v) for v in value]
    return value


def _setting_value(obj: Any, value: Any) -> Any:
    if obj.key in ("security.smtp", "security.green_api") and value:
        from app.security.crypto import decrypt

        try:
            return safe_value("value", json.loads(decrypt(get_settings().key_bytes, value)))
        except (ValueError, TypeError):
            return "[redacted]"
    return safe_value(
        "value", value, obj.is_secret or obj.key.startswith(("security.", "internal."))
    )


def _snapshot(obj: Any) -> dict[str, Any]:
    state = inspect(obj)
    result = {}
    for column in state.mapper.columns:
        name = column.key
        value = getattr(obj, name, None)
        secret = (
            type(obj).__name__ == "Setting"
            and name == "value"
            and (bool(obj.is_secret) or obj.key.startswith(("security.", "internal.")))
        )
        result[name] = (
            _setting_value(obj, value)
            if type(obj).__name__ == "Setting" and name == "value"
            else safe_value(name, value, secret)
        )
    return result


def _flush(session: Session, _: Any, __: Any) -> None:
    if _context.get() is None:
        return
    staged = session.info.setdefault("audit_staged", [])
    for obj in (*session.new, *session.dirty, *session.deleted):
        model = type(obj).__name__
        if model not in _SAFE_MODELS:
            continue
        state = inspect(obj)
        identity = getattr(obj, "key", None) or getattr(obj, "id", None) or str(state.identity)
        if model == "Setting" and obj in session.new:
            from app.settings_store import REGISTRY

            spec = REGISTRY.get(obj.key)
            if spec:
                staged.append(
                    {
                        "entity": model,
                        "id": obj.key,
                        "field": "value",
                        "before": _setting_value(obj, spec.default),
                        "after": _setting_value(obj, obj.value),
                    }
                )
                continue
        if obj in session.new or obj in session.deleted:
            staged.append(
                {
                    "entity": model,
                    "id": str(identity),
                    "action": "created" if obj in session.new else "deleted",
                    "before": None if obj in session.new else _snapshot(obj),
                    "after": _snapshot(obj) if obj in session.new else None,
                    "_created_obj": obj if obj in session.new else None,
                }
            )
        else:
            for attr in state.attrs:
                history = attr.history
                if not history.has_changes():
                    continue
                name = attr.key
                secret = (
                    model == "Setting"
                    and name == "value"
                    and (obj.is_secret or obj.key.startswith(("security.", "internal.")))
                )
                before = history.deleted[0] if history.deleted else None
                after = history.added[0] if history.added else getattr(obj, name, None)
                staged.append(
                    {
                        "entity": model,
                        "id": str(identity),
                        "field": name,
                        "before": _setting_value(obj, before)
                        if model == "Setting" and name == "value"
                        else safe_value(name, before, secret),
                        "after": _setting_value(obj, after)
                        if model == "Setting" and name == "value"
                        else safe_value(name, after, secret),
                    }
                )


def _bulk(state: ORMExecuteState) -> None:
    if _context.get() is None or not (state.is_update or state.is_delete):
        return
    mapper = state.bind_arguments.get("mapper")
    if mapper is None or mapper.class_.__name__ not in _SAFE_MODELS:
        return
    # Bulk operations do not emit attribute histories. Capture identifiers and
    # the exact safe columns being changed before SQL executes.
    statement = cast(Any, state.statement)
    rows = state.session.scalars(select(mapper.class_).where(*statement._where_criteria)).all()
    staged = state.session.info.setdefault("audit_staged", [])
    for obj in rows:
        before = _snapshot(obj)
        changes = {}
        for column, expression in (getattr(statement, "_values", None) or {}).items():
            name = getattr(column, "key", str(column))
            changes[name] = safe_value(name, getattr(expression, "value", "[updated]"))
        staged.append(
            {
                "entity": mapper.class_.__name__,
                "id": str(before.get("id", before.get("key"))),
                "action": "deleted" if state.is_delete else "updated",
                "before": before,
                "after": None if state.is_delete else {**before, **changes},
            }
        )


def _commit(session: Session) -> None:
    changes = _context.get()
    staged = session.info.pop("audit_staged", [])
    if changes is not None:
        changes.extend(staged)


def _created_ids(session: Session, _: Any) -> None:
    for entry in session.info.get("audit_staged", []):
        obj = entry.pop("_created_obj", None)
        if obj is not None:
            entry["id"] = str(getattr(obj, "key", None) or getattr(obj, "id", None))
            entry["after"] = _snapshot(obj)


def install() -> None:
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _flush)
    event.listen(Session, "after_flush_postexec", _created_ids)
    event.listen(Session, "do_orm_execute", _bulk)
    event.listen(Session, "after_commit", _commit)
    event.listen(Session, "after_rollback", lambda session: session.info.pop("audit_staged", None))
    _installed = True


class AuditMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE")
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/api/settings/alert-readiness":
            await self.app(scope, receive, send)
            return
        changes: list[dict[str, Any]] = []
        token = _context.set(changes)
        status = 500

        async def capture(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            _context.reset(token)
            request = Request(scope)
            safe_path = scope["path"]
            for name, value in scope.get("path_params", {}).items():
                if isinstance(value, str) and not value.isdecimal():
                    safe_path = safe_path.replace(value, "{" + name + "}")
            actor = scope.get("audit_actor")
            if actor is None:
                cookie = request.cookies.get(COOKIE_NAME)
                parsed = read_session_token(get_settings(), cookie) if cookie else None
                if parsed:
                    async with request.app.state.session_factory() as db:
                        user = await db.get(User, parsed[0])
                        if user and parsed[1] == user_fingerprint(user):
                            actor = (user.id, user.username)
            try:
                async with request.app.state.session_factory() as db:
                    db.add(
                        AuditLog(
                            user_id=actor[0] if actor else None,
                            username=actor[1] if actor else "Unauthenticated",
                            method=scope["method"],
                            path=safe_path,
                            status_code=status,
                            changes=changes,
                        )
                    )
                    await db.commit()
            except Exception:
                logger.exception("Could not persist user action audit")
