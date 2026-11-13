import hashlib
import json

import httpx
import pytest
import respx

from app.classify.community import guidance, load_pack, public_manifest
from app.classify.evaluation import evaluate_community, metrics, promotion_gate
from app.classify.evaluation_state import configuration_fingerprint
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY, paired_comparison
from app.classify.thresholds import DEFAULT_THRESHOLDS
from scripts.prepare_learning_model import prepare
from scripts.train_learning_adapter import validate


def test_public_pack_has_independent_languages_and_splits():
    pack = load_pack()
    assert public_manifest()["contains_user_data"] is False
    assert len(guidance("שלום")) == len(guidance("hello")) == 6
    assert {e["content"] for e in pack["examples"]}.isdisjoint(
        {e["content"] for e in pack["evaluation"]}
    )
    assert all("message_id" not in e for e in guidance("שלום"))


def test_training_rejects_private_content_even_with_forged_checksum(tmp_path):
    prepare(tmp_path, "test/model", "0" * 40)
    assert validate(tmp_path)["publishable_weights"] is False
    file = tmp_path / "train.jsonl"
    records = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    records[0]["messages"][1]["content"] = "A private conversation without identifiers"
    raw = ("\n".join(json.dumps(r) for r in records) + "\n").encode()
    file.write_bytes(raw)
    manifest_file = tmp_path / "training-manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["datasets"]["train.jsonl"]["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reviewed synthetic pack"):
        validate(tmp_path)


def test_gate_rejects_synthetic_small_regressed_and_equal_candidates():
    rows = [
        {"human": "harmful", "baseline": "harmful", "candidate": "harmful", "conversation": i}
        for i in range(50)
    ]
    rows += [
        {"human": "safe", "baseline": "safe", "candidate": "safe", "conversation": i + 50}
        for i in range(50)
    ]
    report = {
        "source": "held_out_human_reviews",
        "model_identity": {"classifier": "a" * 64},
        "baseline": metrics(rows, "baseline"),
        "candidate": metrics(rows, "candidate"),
        "failures": 0,
        "paired": paired_comparison(rows, unit="conversation"),
        "languages": {
            "he": {"baseline": metrics(rows, "baseline"), "candidate": metrics(rows, "candidate")}
        },
    }
    assert not promotion_gate(report)["eligible"]  # equal is not evidence of improvement
    for i in range(5):
        rows[i] = {
            "human": "harmful",
            "baseline": "safe",
            "candidate": "harmful",
            "conversation": i,
        }
    report["baseline"] = metrics(rows, "baseline")
    report["paired"] = paired_comparison(rows, unit="conversation")
    report["languages"]["he"]["baseline"] = metrics(rows, "baseline")
    assert promotion_gate(report)["eligible"]
    assert not promotion_gate({**report, "source": "synthetic"})["eligible"]
    assert not promotion_gate({**report, "failures": 1})["eligible"]
    report["candidate"] = metrics(rows[:3], "candidate")
    assert not promotion_gate(report)["eligible"]


@respx.mock
async def test_evaluation_is_aggregate_only_and_never_promotes_synthetic():
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
        )
    )
    report = await evaluate_community("model", "http://ollama")
    assert report["evaluated"] == len(load_pack()["evaluation"]) and report["failures"] == 0
    assert len(route.calls) == 2 * len(load_pack()["evaluation"])
    assert report["languages"]["he"]["candidate"]["samples"] == len(load_pack()["evaluation"]) // 2
    assert report["candidate"]["false_negative"] == sum(
        e["verdict"] == "harmful" for e in load_pack()["evaluation"]
    )
    assert report["promotion"]["eligible"] is False
    assert not any(e["content"] in json.dumps(report) for e in load_pack()["evaluation"])


@respx.mock
async def test_checkpoint_finishes_all_cases_without_repeating_completed_pairs():
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
        )
    )
    checkpoint = {}
    for completed in range(1, len(load_pack()["evaluation"]) + 1):
        report = await evaluate_community("model", "http://ollama", checkpoint=checkpoint)
        assert report["evaluated"] == completed
        assert report["pending"] == len(load_pack()["evaluation"]) - completed
    assert len(route.calls) == 2 * len(load_pack()["evaluation"])
    assert report["failures"] == 0
    assert not report["promotion"]["eligible"]
    await evaluate_community("model", "http://ollama", checkpoint=checkpoint)
    assert len(route.calls) == 2 * len(load_pack()["evaluation"])


@respx.mock
async def test_checkpoint_bounds_retries_and_reports_only_safe_error_types():
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(503, text="private provider diagnostic")
    )
    checkpoint = {}
    for _ in range(3 * len(load_pack()["evaluation"])):
        report = await evaluate_community("model", "http://ollama", checkpoint=checkpoint)
    assert report["pending"] == 0 and report["failures"] == len(load_pack()["evaluation"])
    assert len(route.calls) == 3 * len(load_pack()["evaluation"])
    assert "private provider diagnostic" not in json.dumps(report)
    assert sum(report["request_errors"].values()) == 3 * len(load_pack()["evaluation"])


@respx.mock
async def test_evaluation_job_resumes_durably_without_consuming_retries(app_client, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from app.classify.evaluation import RESULT_KEY, evaluate_job
    from app.db.models import Job, Setting
    from app.jobs import queue
    from app.jobs.worker import run_one

    monkeypatch.setattr(
        "app.classify.evaluation.get_settings",
        lambda: SimpleNamespace(
            classification_provider="ollama",
            ollama_model="model",
            ollama_context_tokens=16384,
            ollama_output_tokens=2048,
            ollama_base_url="http://ollama",
            job_timeout_seconds=900,
        ),
    )
    respx.get("http://ollama/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "model:latest", "digest": "a" * 64}]}
        )
    )
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
        )
    )
    factory = app_client.app.state.session_factory
    async with factory() as db:
        jid = await queue.enqueue(db, "evaluate_learning", {"source": "synthetic"}, max_attempts=1)
    for case in range(len(load_pack()["evaluation"])):
        claimed = await queue.claim(factory)
        assert claimed is not None and claimed.id == jid
        state = await run_one(
            claimed, SimpleNamespace(session_factory=factory), {"evaluate_learning": evaluate_job}
        )
        assert state == ("done" if case == len(load_pack()["evaluation"]) - 1 else "queued")
        async with factory() as db:
            result = await db.get(Setting, RESULT_KEY)
            assert result.value["evaluated"] == case + 1
            stored = await db.get(Job, jid)
            if case < len(load_pack()["evaluation"]) - 1:
                assert stored.attempts == 0
                stored.run_after = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
                await db.commit()
    assert len(route.calls) == 2 * len(load_pack()["evaluation"])


async def test_evaluation_queue_validates_source_and_reuses_pending_job(app_client):
    first = await app_client.post("/api/learning/evaluation?source=held_out_human_reviews")
    assert first.status_code == 200
    second = await app_client.post("/api/learning/evaluation?source=synthetic")
    assert second.json() == first.json()
    status = (await app_client.get("/api/learning/evaluation")).json()
    assert status["running"] and status["result"] is None
    assert (
        await app_client.post("/api/learning/evaluation?source=private_export")
    ).status_code == 422


@pytest.mark.parametrize("source", ["synthetic", "held_out_human_reviews"])
async def test_old_pack_result_is_marked_stale_without_discarding_history(
    app_client, source, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.classify.evaluation import RESULT_KEY
    from app.db.models import Setting
    from app.settings_store import set_setting

    monkeypatch.setattr(
        "app.api.learning.resolve_identity", AsyncMock(return_value={"classifier": "a" * 64})
    )
    factory = app_client.app.state.session_factory
    async with factory() as db:
        await set_setting(db, "runtime.classification_provider", "ollama")
        db.add(
            Setting(
                key=RESULT_KEY,
                value={"source": source, "pack": {"sha256": "old"}, "evaluated": 12},
            )
        )
        await db.commit()
    status = (await app_client.get("/api/learning/evaluation")).json()
    assert status["stale"] and status["result"]["evaluated"] == 12
    async with factory() as db:
        row = await db.get(Setting, RESULT_KEY)
        row.value = {
            **row.value,
            "model_identity": {"classifier": "a" * 64},
            "configuration_sha256": await configuration_fingerprint(db),
            "pack": public_manifest(),
            "quality_policy": QUALITY_POLICY,
            "prompt_sha256": prompt_fingerprint(),
        }
        await db.commit()
    assert not (await app_client.get("/api/learning/evaluation")).json()["stale"]


async def test_sharing_requires_explicit_revocable_account_consent(app_client):
    assert (await app_client.get("/api/auth/learning-sharing")).json()["enabled"] is False
    denied = await app_client.patch("/api/auth/learning-sharing", json={"enabled": True})
    assert denied.status_code == 422
    approved = await app_client.patch(
        "/api/auth/learning-sharing",
        json={
            "enabled": True,
            "acknowledged_policy": "synthetic-only-v1",
        },
    )
    assert approved.json() == {
        "enabled": True,
        "policy": "synthetic-only-v1",
        "automatic_upload": False,
    }
    assert (await app_client.get("/api/auth/learning-sharing")).json()["enabled"] is True
    revoked = await app_client.patch("/api/auth/learning-sharing", json={"enabled": False})
    assert revoked.json()["enabled"] is False


async def test_report_history_is_bounded_and_does_not_archive_partial_progress(
    app_client, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.classify.evaluation_state import HISTORY_KEY, save_report
    from app.db.models import Setting
    from app.settings_store import set_setting

    monkeypatch.setattr(
        "app.api.learning.resolve_identity", AsyncMock(return_value={"classifier": "a" * 64})
    )
    factory = app_client.app.state.session_factory
    async with factory() as db:
        await set_setting(db, "runtime.classification_provider", "ollama")
        configuration = await configuration_fingerprint(db)
        for i in range(12):
            report = {
                "evaluation_id": str(i),
                "source": "held_out_human_reviews",
                "model_identity": {"classifier": "a" * 64},
                "configuration_sha256": configuration,
                "quality_policy": QUALITY_POLICY,
                "prompt_sha256": prompt_fingerprint(),
                "evaluated": i,
                "pending": 0,
            }
            await save_report(db, report)
            await db.commit()
        await save_report(db, {**report, "evaluation_id": "next", "pending": 3})
        await db.commit()
        history = await db.get(Setting, HISTORY_KEY)
        assert len(history.value) == 10
        assert [r["evaluation_id"] for r in history.value] == [str(i) for i in range(11, 1, -1)]
    status = (await app_client.get("/api/learning/evaluation")).json()
    assert not status["stale"] and all(not r["stale"] for r in status["history"])
    assert status["result"]["pending"] == 3
    async with factory() as db:
        await set_setting(db, "runtime.ollama_model", "another-model")
        await db.commit()
    status = (await app_client.get("/api/learning/evaluation")).json()
    assert status["stale"] and all(r["stale"] for r in status["history"])
    assert len(status["history"]) == 10
