import hashlib
import json

import httpx
import pytest
import respx

from app.classify.community import guidance, load_pack, public_manifest
from app.classify.evaluation import evaluate_community, metrics, promotion_gate
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
    prepare(tmp_path, "local-base", "pinned-revision")
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
    rows = [{"human": "harmful", "baseline": "harmful", "candidate": "harmful"}] * 50
    rows += [{"human": "safe", "baseline": "safe", "candidate": "safe"}] * 50
    report = {
        "source": "held_out_human_reviews",
        "baseline": metrics(rows, "baseline"),
        "candidate": metrics(rows, "candidate"),
        "failures": 0,
    }
    assert not promotion_gate(report)["eligible"]  # equal is not evidence of improvement
    rows[0] = {"human": "harmful", "baseline": "safe", "candidate": "harmful"}
    report["baseline"] = metrics(rows, "baseline")
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
    assert report["evaluated"] == 12 and report["failures"] == 0
    assert len(route.calls) == 24
    assert report["languages"]["he"]["candidate"]["samples"] == 6
    assert report["candidate"]["false_negative"] == 8
    assert report["promotion"]["eligible"] is False
    assert not any(e["content"] in json.dumps(report) for e in load_pack()["evaluation"])


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
