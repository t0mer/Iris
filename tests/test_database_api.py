import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from loguru import logger
from sqlalchemy import func, select

from app.api import database as dbapi
from app.config import get_settings
from app.db import url as dburl
from app.db.models import Instance, Message
from app.db.url import DbConfig
from tests.test_webhooks import fx, make_instance, post

PG_BODY = {
    "kind": "postgresql",
    "host": "db.local",
    "port": 5432,
    "name": "iris",
    "user": "iris",
    "password": "s3cret-pw",
    "tls": False,
}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    dbapi._recent.clear()
    monkeypatch.delenv("IRIS_DATABASE_URL", raising=False)


@pytest.fixture
def probe_ok(monkeypatch: pytest.MonkeyPatch) -> list[DbConfig]:
    seen: list[DbConfig] = []

    async def fake(cfg: DbConfig) -> dbapi.ProbeResult:
        seen.append(cfg)
        return dbapi.ProbeResult(ok=True, detail="Connected.", version="16.1", empty=True)

    monkeypatch.setattr(dbapi, "_probe", fake)
    return seen


async def test_requires_a_login(app_client: Any) -> None:
    app_client.cookies.clear()
    assert (await app_client.get("/api/database")).status_code == 401
    assert (await app_client.post("/api/database/test", json=PG_BODY)).status_code == 401
    assert (await app_client.put("/api/database", json=PG_BODY)).status_code == 401
    assert (await app_client.delete("/api/database")).status_code == 401
    assert (await app_client.post("/api/database/copy")).status_code == 401


async def test_status_defaults_to_sqlite(app_client: Any) -> None:
    s = (await app_client.get("/api/database")).json()
    assert s["running"]["kind"] == "sqlite" and s["running_source"] == "default"
    assert s["saved"]["kind"] == "sqlite"
    assert s["restart_required"] is False and s["env_override"] is False
    assert s["copy_job"]["state"] == "idle"


async def test_save_writes_the_file_and_asks_for_a_restart(
    app_client: Any, probe_ok: list[DbConfig]
) -> None:
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        r = await app_client.put("/api/database", json=PG_BODY)
    finally:
        logger.remove(sink)
    s = r.json()
    assert r.status_code == 200 and s["restart_required"] is True
    assert s["running"]["kind"] == "sqlite" and s["saved"]["kind"] == "postgresql"
    assert s["saved"]["password_set"] is True and "s3cret-pw" not in r.text
    assert "s3cret-pw" not in dburl.config_path().read_text()
    assert "s3cret-pw" not in "".join(lines)
    assert (await app_client.get("/api/database")).json()["saved"]["host"] == "db.local"
    assert "s3cret-pw" not in (await app_client.get("/api/database")).text


async def test_a_blank_password_keeps_the_saved_one(
    app_client: Any, probe_ok: list[DbConfig]
) -> None:
    await app_client.put("/api/database", json=PG_BODY)
    await app_client.post("/api/database/test", json={**PG_BODY, "password": ""})
    assert probe_ok[-1].password == "s3cret-pw"
    await app_client.put("/api/database", json={**PG_BODY, "password": None, "tls": True})
    assert dburl.load_file() == DbConfig(**{**PG_BODY, "tls": True})  # same server: kept
    # a different account does not inherit the stored password
    await app_client.post("/api/database/test", json={**PG_BODY, "password": "", "user": "bob"})
    assert probe_ok[-1].password == ""


async def test_a_failed_connection_is_not_saved(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(cfg: DbConfig) -> dbapi.ProbeResult:
        return dbapi.ProbeResult(ok=False, detail="The user name or password was refused.")

    monkeypatch.setattr(dbapi, "_probe", fake)
    r = await app_client.put("/api/database", json=PG_BODY)
    assert r.status_code == 422 and "refused" in r.json()["detail"]
    assert not dburl.config_path().exists()


async def test_invalid_input_is_explained_without_connecting(
    app_client: Any, probe_ok: list[DbConfig]
) -> None:
    r = await app_client.post("/api/database/test", json={**PG_BODY, "host": "bad host!"})
    assert r.json()["ok"] is False and "host" in r.json()["detail"].lower()
    r = await app_client.post("/api/database/test", json={**PG_BODY, "name": ""})
    assert r.json()["ok"] is False and "database name" in r.json()["detail"]
    assert probe_ok == []
    assert (
        await app_client.post("/api/database/test", json={**PG_BODY, "port": 0})
    ).status_code == 422


async def test_an_unreachable_server_gets_a_plain_reason(app_client: Any) -> None:
    r = await app_client.post(
        "/api/database/test", json={**PG_BODY, "host": "127.0.0.1", "port": 1}
    )
    d = r.json()
    assert d["ok"] is False and "Could not reach the server" in d["detail"]
    assert "s3cret-pw" not in r.text


async def test_sqlite_probe_works_and_saving_sqlite_forgets_the_file(app_client: Any) -> None:
    r = await app_client.post("/api/database/test", json={"kind": "sqlite"})
    assert r.json()["ok"] is True and r.json()["version"]
    dburl.save_file(DbConfig(kind="postgresql", host="h", name="n", user="u"))
    r = await app_client.put("/api/database", json={"kind": "sqlite"})
    assert r.status_code == 200 and not dburl.config_path().exists()
    assert r.json()["restart_required"] is False


async def test_env_override_blocks_changes_but_is_reported(
    app_client: Any, monkeypatch: pytest.MonkeyPatch, probe_ok: list[DbConfig]
) -> None:
    monkeypatch.setenv("IRIS_DATABASE_URL", "postgresql://u:p@envhost/db")
    s = (await app_client.get("/api/database")).json()
    assert s["env_override"] is True and s["saved"]["host"] == "envhost"
    assert (await app_client.put("/api/database", json=PG_BODY)).status_code == 409
    assert (await app_client.delete("/api/database")).status_code == 409
    assert not dburl.config_path().exists()


async def test_use_sqlite_again_removes_the_choice(
    app_client: Any, probe_ok: list[DbConfig]
) -> None:
    await app_client.put("/api/database", json=PG_BODY)
    r = await app_client.delete("/api/database")
    assert r.status_code == 200 and r.json()["restart_required"] is False
    assert not dburl.config_path().exists()


async def test_testing_is_rate_limited(app_client: Any, probe_ok: list[DbConfig]) -> None:
    for _ in range(dbapi.MAX_TESTS):
        assert (await app_client.post("/api/database/test", json=PG_BODY)).status_code == 200
    assert (await app_client.post("/api/database/test", json=PG_BODY)).status_code == 429


# --- copy -----------------------------------------------------------------------------------


async def _seed(app_client: Any) -> None:
    _, token = await make_instance(app_client)
    await post(app_client, token, fx("text_received_mixed"))
    await post(app_client, token, fx("text_sent_he"))


async def _wait_copy(app_client: Any) -> dict[str, Any]:
    for _ in range(100):
        s = (await app_client.get("/api/database/copy")).json()
        if s["state"] in ("done", "failed"):
            return s  # type: ignore[no-any-return]
        await asyncio.sleep(0.1)
    raise AssertionError("copy did not finish")


def _target(tmp_path: Path, name: str = "new.db") -> DbConfig:
    return DbConfig(kind="sqlite", name=str(tmp_path / name))


async def test_copy_needs_a_different_saved_database(app_client: Any) -> None:
    r = await app_client.post("/api/database/copy")
    assert r.status_code == 409


async def test_copy_moves_every_row_and_leaves_the_source_alone(
    app_client: Any, tmp_path: Path
) -> None:
    await _seed(app_client)
    target = _target(tmp_path)
    dburl.save_file(target)
    assert (await app_client.post("/api/database/copy")).status_code == 202
    done = await _wait_copy(app_client)
    assert done["state"] == "done" and done["copied"]["messages"] == 2
    assert done["copied"]["instances"] == 1 and done["error"] is None

    from app.db.engine import make_engine, make_session_factory

    engine = make_engine(config=target)
    async with make_session_factory(engine)() as s:
        assert (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 2
        inst = (await s.execute(select(Instance))).scalar_one()
        assert inst.openwa_api_key_enc is None or isinstance(inst.openwa_api_key_enc, str)
    await engine.dispose()
    async with app_client.app.state.session_factory() as s:
        assert (await s.execute(select(func.count()).select_from(Message))).scalar_one() == 2


async def test_copy_refuses_a_target_that_already_has_data(app_client: Any, tmp_path: Path) -> None:
    await _seed(app_client)
    target = _target(tmp_path)
    dburl.save_file(target)
    await app_client.post("/api/database/copy")
    assert (await _wait_copy(app_client))["state"] == "done"
    again = await app_client.post("/api/database/copy")
    assert again.status_code == 202
    failed = await _wait_copy(app_client)
    assert failed["state"] == "failed" and "already contains data" in failed["error"]


async def test_the_copy_keeps_ids_and_settings_secrets_readable(
    app_client: Any, tmp_path: Path
) -> None:
    await app_client.put("/api/settings", json={"settings": {"openai.api_key": "sk-secret"}})
    await _seed(app_client)
    target = _target(tmp_path)
    dburl.save_file(target)
    await app_client.post("/api/database/copy")
    assert (await _wait_copy(app_client))["state"] == "done"

    from app.db.engine import make_engine, make_session_factory
    from app.settings_store import get_secret

    engine = make_engine(config=target)
    async with make_session_factory(engine)() as s:
        assert await get_secret(s, "openai.api_key", get_settings().key_bytes) == "sk-secret"
        ids = [m.id for m in (await s.execute(select(Message).order_by(Message.id))).scalars()]
    await engine.dispose()
    async with app_client.app.state.session_factory() as s:
        src = [m.id for m in (await s.execute(select(Message).order_by(Message.id))).scalars()]
    assert ids == src


async def test_the_copy_never_exposes_the_password_it_used(app_client: Any, tmp_path: Path) -> None:
    dburl.save_file(
        DbConfig(kind="postgresql", host="127.0.0.1", port=1, name="n", user="u", password="pw-123")
    )
    r = await app_client.post("/api/database/copy")
    assert r.status_code == 202
    failed = await _wait_copy(app_client)
    assert failed["state"] == "failed" and "pw-123" not in json.dumps(failed)


# --- review findings --------------------------------------------------------------------------


async def test_a_stored_password_is_not_sent_to_a_different_server(
    app_client: Any, probe_ok: list[DbConfig]
) -> None:
    await app_client.put("/api/database", json=PG_BODY)
    for change in ({"host": "other.example"}, {"port": 6543}, {"name": "elsewhere"}):
        await app_client.post("/api/database/test", json={**PG_BODY, "password": "", **change})
        assert probe_ok[-1].password == "", change
    await app_client.post("/api/database/test", json={**PG_BODY, "password": ""})
    assert probe_ok[-1].password == "s3cret-pw"  # the very same server keeps it


async def test_an_unreadable_saved_choice_is_reported_not_swallowed(
    app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    dburl.config_path().write_text("{ not json", encoding="utf-8")
    with pytest.raises(dburl.DbConfigError) as err:
        dburl.resolve()
    assert "cannot be read" in str(err.value) and "IRIS_SECRET_KEY" in str(err.value)
    s = (await app_client.get("/api/database")).json()
    assert "cannot be read" in s["config_error"] and s["restart_required"] is False


async def test_a_file_saved_with_another_key_names_the_cause_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64

    dburl.save_file(DbConfig(kind="postgresql", host="h", name="n", user="u", password="pw-9"))
    monkeypatch.setenv("IRIS_SECRET_KEY", base64.b64encode(b"z" * 32).decode())
    get_settings.cache_clear()
    with pytest.raises(dburl.DbConfigError) as err:
        dburl.resolve()
    assert "pw-9" not in str(err.value)


async def test_saving_a_new_choice_forgets_the_old_copy_result(
    app_client: Any, tmp_path: Path, probe_ok: list[DbConfig]
) -> None:
    await _seed(app_client)
    dburl.save_file(_target(tmp_path))
    await app_client.post("/api/database/copy")
    assert (await _wait_copy(app_client))["state"] == "done"
    await app_client.put("/api/database", json=PG_BODY)
    assert (await app_client.get("/api/database")).json()["copy_job"]["state"] == "idle"


async def test_the_probe_calls_a_migrated_but_empty_database_empty(tmp_path: Path) -> None:
    from app.db.engine import make_engine, make_session_factory
    from app.db.migrate import upgrade_head
    from app.db.models import Chat

    path = tmp_path / "probe.db"
    await asyncio.to_thread(upgrade_head, f"sqlite+aiosqlite:///{path}")
    cfg = DbConfig(kind="sqlite", name=str(path))
    assert (await dbapi._probe(cfg)).empty is True  # tables exist, no rows
    engine = make_engine(config=cfg)
    async with make_session_factory(engine)() as s:
        s.add(Chat(wa_chat_id="c", name="x"))
        await s.commit()
    await engine.dispose()
    r = await dbapi._probe(cfg)
    assert r.empty is False and "already holds Iris data" in r.detail


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ('database "iris" does not exist', "That database does not exist"),
        ('role "bob" does not exist', "Could not connect"),
        ("password authentication failed for user", "user name or password was refused"),
        ("Access denied for user 'u'@'h' (1045)", "user name or password was refused"),
        ("Unknown database 'iris' (1049)", "That database does not exist"),
    ],
)
def test_reasons_are_specific_and_never_the_driver_text(message: str, expected: str) -> None:
    exc = RuntimeError("driver text")
    exc.orig = RuntimeError(message)  # type: ignore[attr-defined]  # how SQLAlchemy wraps drivers
    why = dbapi._why(exc)
    assert expected in why and "bob" not in why and "iris" not in why.replace("Iris", "")


# --- the copy under stress ------------------------------------------------------------------


async def test_a_failed_copy_leaves_the_target_empty_so_it_can_be_retried(
    app_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import copy as dbcopy

    await _seed(app_client)
    dburl.save_file(_target(tmp_path))
    real = dbcopy._copy_table

    async def flaky(src: Any, target: Any, table: Any) -> int:
        if table.name == "message_receipts":
            raise OSError("connection reset by peer")
        return await real(src, target, table)

    monkeypatch.setattr(dbcopy, "_copy_table", flaky)
    await app_client.post("/api/database/copy")
    failed = await _wait_copy(app_client)
    assert failed["state"] == "failed" and "OSError" in failed["error"]
    assert "connection reset" not in failed["error"]

    monkeypatch.setattr(dbcopy, "_copy_table", real)  # the server recovered
    await app_client.post("/api/database/copy")
    assert (await _wait_copy(app_client))["state"] == "done"


async def test_writes_during_the_copy_do_not_break_it(
    app_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import copy as dbcopy
    from app.db.models import MessageReceipt

    await _seed(app_client)
    dburl.save_file(_target(tmp_path))
    real = dbcopy._copy_table

    async def writes_in_between(src: Any, target: Any, table: Any) -> int:
        n = await real(src, target, table)
        if table.name == "messages":  # a webhook lands after the messages were copied
            async with app_client.app.state.session_factory() as s:
                chat_id = (await s.execute(select(Message.chat_id))).scalars().first()
                s.add(
                    Message(
                        wa_message_id="late",
                        chat_id=chat_id,
                        type="text",
                        text="late",
                        sent_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    )
                )
                await s.flush()
                late = (
                    await s.execute(select(Message).where(Message.wa_message_id == "late"))
                ).scalar_one()
                inst = (await s.execute(select(Instance.id))).scalars().first()
                s.add(MessageReceipt(message_id=late.id, instance_id=inst))
                await s.commit()
        return n

    monkeypatch.setattr(dbcopy, "_copy_table", writes_in_between)
    await app_client.post("/api/database/copy")
    done = await _wait_copy(app_client)
    assert done["state"] == "done", done
    assert done["copied"]["messages"] == 2 and done["copied"]["message_receipts"] == 2


async def test_the_copy_migrates_the_target_with_its_own_settings(
    app_client: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import copy as dbcopy

    seen: list[Any] = []
    real = dbcopy.upgrade_head
    monkeypatch.setattr(dbcopy, "upgrade_head", lambda *a: (seen.append(a), real(*a))[1])
    target = DbConfig(kind="sqlite", name=str(tmp_path / "tls.db"), tls=True)
    dburl.save_file(target)
    await app_client.post("/api/database/copy")
    assert (await _wait_copy(app_client))["state"] == "done"
    assert seen and seen[0][0] is None and seen[0][1] == target  # TLS and timeouts travel along


async def test_nullable_json_columns_store_sql_null(app_client: Any) -> None:
    from sqlalchemy import text

    await _seed(app_client)
    async with app_client.app.state.session_factory() as s:
        m = (await s.execute(select(Message))).scalars().first()
        assert m is not None
        m.media = None
        await s.commit()
        n = (
            await s.execute(text("SELECT count(*) FROM messages WHERE media IS NULL"))
        ).scalar_one()
        assert n >= 1
