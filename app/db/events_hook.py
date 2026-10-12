"""Publishes a live-update event after every committed change, from the tables it touched."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session

from app.events import bus

# table (model class name) -> the parts of the portal that show it
TOPICS: dict[str, tuple[str, ...]] = {
    "Message": ("messages", "stats", "review"),
    "Classification": ("messages", "review"),
    "MessageReceipt": ("messages",),
    "MessageRevision": ("messages",),
    "StoredMedia": ("alerts", "messages"),
    "Alert": ("alerts", "stats"),
    "AlertView": ("alerts", "stats"),
    "Job": ("jobs", "stats", "review"),
    "Instance": ("instances", "stats"),
    "Chat": ("chats",),
    "ChatInstance": ("chats",),
    "Setting": ("stats",),
    "User": ("stats",),
    "ReviewResponse": ("review", "alerts", "stats"),
    "ReviewFeedback": ("review", "alerts", "stats"),
    "ScheduleRun": ("stats",),
}
_KEY = "iris_live"
_installed = False


def _clear_withheld_feedback(session: Session, _ctx: Any, _instances: Any) -> None:
    from app.db.models import Message, ReviewFeedback

    for message in list(session.dirty):
        if isinstance(message, Message) and (message.redacted or message.revoked_at):
            feedback = session.get(ReviewFeedback, message.id)
            if feedback:
                feedback.explanation = None
                feedback.categories = None
            for pending in list(session.new):
                if isinstance(pending, ReviewFeedback) and pending.message_id == message.id:
                    pending.explanation = None
                    pending.categories = None


def _state(session: Session) -> dict[str, Any]:
    state: dict[str, Any] = session.info.setdefault(_KEY, {"topics": set(), "alerts": []})
    return state


def _on_execute(execute_state: ORMExecuteState) -> None:
    """Bulk update()/delete() skip the unit of work, so read the table off the statement."""
    if not (execute_state.is_update or execute_state.is_delete or execute_state.is_insert):
        return
    mapper = execute_state.bind_arguments.get("mapper")
    if mapper is not None:
        _state(execute_state.session)["topics"].update(TOPICS.get(mapper.class_.__name__, ()))


def _after_flush(session: Session, _ctx: Any) -> None:
    state = _state(session)
    for obj in (*session.new, *session.dirty, *session.deleted):
        state["topics"].update(TOPICS.get(type(obj).__name__, ()))
    for obj in session.new:
        if type(obj).__name__ == "Alert":
            state["alerts"].append(obj.id)  # the primary key exists after the flush


def _after_commit(session: Session) -> None:
    state = session.info.pop(_KEY, None)
    if state is None:
        return
    for alert_id in state["alerts"] or [None]:
        bus.publish(*state["topics"], alert_id=alert_id)


def _after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)  # nothing was committed, so nothing changed


def install() -> None:
    """Hook every session (async sessions run on the sync Session class). Idempotent."""
    global _installed
    if _installed:
        return
    event.listen(Session, "do_orm_execute", _on_execute)
    event.listen(Session, "before_flush", _clear_withheld_feedback)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)
    _installed = True
