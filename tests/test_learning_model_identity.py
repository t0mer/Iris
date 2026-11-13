import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.classify.evaluation import RESULT_KEY, evaluate_job
from app.classify.evaluation_state import configuration_fingerprint
from app.classify.model_identity import ModelIdentityError, resolve_identity
from app.classify.prompt import prompt_fingerprint
from app.classify.quality import QUALITY_POLICY
from app.classify.thresholds import DEFAULT_THRESHOLDS
from app.db.models import Job, Setting
from app.jobs import queue
from app.jobs.worker import run_one
from app.settings_store import set_setting


def tags(digest="a" * 64):
    return httpx.Response(200, json={"models": [{"name": "model:latest", "digest": digest}]})


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"name": "model", "digest": "bad"}],
        [{"name": "model", "digest": None}],
        [{"name": "model", "digest": "a" * 64}, {"name": "model:latest", "digest": "b" * 64}],
        {"private": "diagnostic"},
    ],
)
@respx.mock
async def test_invalid_or_ambiguous_identity_fails_closed(rows):
    respx.get("http://ollama/api/tags").mock(
        return_value=httpx.Response(200, json={"models": rows})
    )
    with pytest.raises(ModelIdentityError) as error:
        await resolve_identity("http://ollama", {"classifier": "model"})
    assert "diagnostic" not in str(error.value)


@respx.mock
async def test_identity_resolves_default_tag_registry_port_and_embedding():
    respx.get("http://ollama/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "registry:5000/team/model:latest", "digest": "sha256:" + "A" * 64},
                    {"name": "embed:v1", "digest": "b" * 64},
                ]
            },
        )
    )
    assert await resolve_identity(
        "http://ollama/", {"classifier": "registry:5000/team/model", "embedding": "embed:v1"}
    ) == {"classifier": "a" * 64, "embedding": "b" * 64}


async def ready(factory, jid):
    async with factory() as db:
        job = await db.get(Job, jid)
        job.run_after = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
        await db.commit()
    claimed = await queue.claim(factory)
    assert claimed is not None and claimed.id == jid
    return claimed


def configure(monkeypatch):
    monkeypatch.setattr(
        "app.classify.evaluation.get_settings",
        lambda: SimpleNamespace(
            classification_provider="ollama",
            ollama_base_url="http://ollama",
            ollama_model="model",
            ollama_context_tokens=16384,
            ollama_output_tokens=2048,
            job_timeout_seconds=900,
        ),
    )


@respx.mock
async def test_changed_model_resets_checkpoint_and_mid_pair_change_cannot_be_committed(
    app_client, monkeypatch
):
    configure(monkeypatch)
    respx.get("http://ollama/api/tags").mock(
        side_effect=[tags(), tags(), tags("b" * 64), tags("b" * 64), tags("b" * 64), tags("c" * 64)]
    )
    route = respx.post("http://ollama/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"content": json.dumps(dict.fromkeys(DEFAULT_THRESHOLDS, 0))}}
        )
    )
    factory = app_client.app.state.session_factory
    async with factory() as db:
        jid = await queue.enqueue(db, "evaluate_learning", {"source": "synthetic"}, max_attempts=3)
    for digest in ("a", "b"):
        claimed = await ready(factory, jid)
        assert (
            await run_one(
                claimed,
                SimpleNamespace(session_factory=factory),
                {"evaluate_learning": evaluate_job},
            )
            == "queued"
        )
        async with factory() as db:
            report = (await db.get(Setting, RESULT_KEY)).value
            assert report["evaluated"] == 1
            assert report["model_identity"] == {"classifier": digest * 64}
    claimed = await ready(factory, jid)
    assert (
        await run_one(
            claimed, SimpleNamespace(session_factory=factory), {"evaluate_learning": evaluate_job}
        )
        == "queued"
    )
    async with factory() as db:
        report = (await db.get(Setting, RESULT_KEY)).value
        job = await db.get(Job, jid)
        assert report["evaluated"] == 1 and report["model_identity"]["classifier"] == "b" * 64
        assert len(job.payload["evaluation_checkpoint"]["rows"]) == 1
        assert "model changed" in job.last_error
    assert len(route.calls) == 6
    assert all(
        json.loads(call.request.content)["options"]["num_predict"] == 2048 for call in route.calls
    )


@respx.mock
async def test_identity_outage_has_bounded_queue_retries_and_safe_diagnostics(
    app_client, monkeypatch
):
    configure(monkeypatch)
    route = respx.get("http://ollama/api/tags").mock(
        return_value=httpx.Response(503, text="private token")
    )
    factory = app_client.app.state.session_factory
    async with factory() as db:
        jid = await queue.enqueue(db, "evaluate_learning", {"source": "synthetic"}, max_attempts=3)
    for expected in ("queued", "queued", "dead"):
        claimed = await ready(factory, jid)
        assert (
            await run_one(
                claimed,
                SimpleNamespace(session_factory=factory),
                {"evaluate_learning": evaluate_job},
            )
            == expected
        )
    async with factory() as db:
        job = await db.get(Job, jid)
        assert "private token" not in job.last_error
        assert await db.get(Setting, RESULT_KEY) is None
    assert len(route.calls) == 3
    assert (await app_client.get("/api/learning/evaluation")).json()["failed"]


@respx.mock
async def test_status_detects_replaced_weights_and_unavailable_identity(app_client):
    factory = app_client.app.state.session_factory
    async with factory() as db:
        await set_setting(db, "runtime.classification_provider", "ollama")
        await set_setting(db, "runtime.ollama_model", "model")
        await set_setting(db, "runtime.ollama_base_url", "http://ollama")
        db.add(
            Setting(
                key=RESULT_KEY,
                value={
                    "source": "synthetic",
                    "configuration_sha256": await configuration_fingerprint(db),
                    "quality_policy": QUALITY_POLICY,
                    "prompt_sha256": prompt_fingerprint(),
                    "model_identity": {"classifier": "a" * 64},
                },
            )
        )
        await db.commit()
    route = respx.get("http://ollama/api/tags").mock(return_value=tags())
    assert not (await app_client.get("/api/learning/evaluation")).json()["stale"]
    route.mock(return_value=tags("b" * 64))
    assert (await app_client.get("/api/learning/evaluation")).json()["stale"]
    route.mock(return_value=httpx.Response(503, text="private token"))
    response = await app_client.get("/api/learning/evaluation")
    assert response.status_code == 200
    assert response.json()["stale"] and response.json()["model_identity_status"] == "unavailable"
    assert "private token" not in response.text


@respx.mock
async def test_concurrent_setting_change_discards_pair(app_client, monkeypatch):
    from unittest.mock import AsyncMock

    from app.classify.quality import metrics

    configure(monkeypatch)
    respx.get("http://ollama/api/tags").mock(return_value=tags())
    factory = app_client.app.state.session_factory

    async def evaluate(*args, **kwargs):
        async with factory() as db:
            await set_setting(db, "classification.context_window_size", 5)
            await db.commit()
        return {
            "source": "synthetic",
            "pending": 0,
            "baseline": metrics([], "baseline"),
            "candidate": metrics([], "candidate"),
        }

    monkeypatch.setattr(
        "app.classify.evaluation.evaluate_community", AsyncMock(side_effect=evaluate)
    )
    async with factory() as db:
        jid = await queue.enqueue(db, "evaluate_learning", {"source": "synthetic"}, max_attempts=3)
    claimed = await ready(factory, jid)
    assert (
        await run_one(
            claimed, SimpleNamespace(session_factory=factory), {"evaluate_learning": evaluate_job}
        )
        == "queued"
    )
    async with factory() as db:
        assert await db.get(Setting, RESULT_KEY) is None
        assert "settings changed" in (await db.get(Job, jid)).last_error
