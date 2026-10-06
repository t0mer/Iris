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
    await app_client.put("/api/database", json={**PG_BODY, "password": None, "name": "other"})
    assert dburl.load_file() == DbConfig(**{**PG_BODY, "name": "other"})
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
