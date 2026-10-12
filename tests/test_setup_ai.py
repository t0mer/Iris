from typing import Any

from app.config import get_settings
from app.security.two_factor import CONFIG_KEY, save
from tests.test_alert_readiness import provider


async def test_ai_tests_use_saved_settings_and_changes_invalidate_proof(
    app_client: Any, monkeypatch: Any
) -> None:
    from app.api.settings import TestResult

    calls = []

    async def test(target: str, db: Any, cfg: Any, body: Any) -> TestResult:
        calls.append((target, body.base_url, body.model))
        return TestResult(ok=True, detail="Synthetic success")

    monkeypatch.setattr("app.api.settings.test_provider", test)
    cfg = get_settings()
    monkeypatch.setattr(cfg, "classification_provider", "ollama")
    monkeypatch.setattr(cfg, "transcription_provider", "local_whisper")
    monkeypatch.setattr(cfg, "whisper_url", "http://whisper.test/v1/audio/transcriptions")
    for target in ("ollama", "local_whisper"):
        assert (await app_client.post(f"/api/setup/ai/test/{target}")).json()["ok"]
    status = (await app_client.get("/api/setup")).json()
    assert next(s for s in status["steps"] if s["id"] == "ai")["ready"]
    assert calls[0] == ("ollama", cfg.ollama_base_url, cfg.ollama_model)
    monkeypatch.setattr(cfg, "ollama_model", "different-model")
    status = (await app_client.get("/api/setup")).json()
    assert not next(s for s in status["steps"] if s["id"] == "ai")["ready"]
    assert not next(p for p in status["ai_providers"] if p["id"] == "ollama")["tested"]


async def test_failed_ai_retest_revokes_success(app_client: Any, monkeypatch: Any) -> None:
    from app.api.settings import TestResult

    passed = True

    async def test(*args: Any) -> TestResult:
        return TestResult(ok=passed, detail="Synthetic result")

    monkeypatch.setattr("app.api.settings.test_provider", test)
    assert (await app_client.post("/api/setup/ai/test/ollama")).json()["ok"]
    passed = False
    assert not (await app_client.post("/api/setup/ai/test/ollama")).json()["ok"]
    status = (await app_client.get("/api/setup")).json()
    assert not next(p for p in status["ai_providers"] if p["id"] == "ollama")["tested"]


async def test_setup_accepts_any_tested_notification_provider(app_client: Any) -> None:
    await provider(app_client, CONFIG_KEY)
    async with app_client.app.state.session_factory() as db:
        # At least one tested provider is enough, even if the active channel differs.
        await save(db, "internal.notifier_test.smtp", "synthetic")
        await db.commit()
    state = (await app_client.get("/api/setup")).json()
    assert state["active_channel"] == "openwa"
    assert next(s for s in state["steps"] if s["id"] == "notifiers")["ready"]
    app_client.cookies.clear()
    assert (await app_client.post("/api/setup/ai/test/ollama")).status_code == 401
